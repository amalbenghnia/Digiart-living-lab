import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict

from app.models.lead import LeadPriority, LeadStatus
from app.repositories.base_repository import LeadRepository
from app.llm.base_provider import LLMProvider
from app.api.schemas.sdr_schema import (
    SDRBriefResponse,
    ObjectionRequest, ObjectionResponse,
    CallOutcome, CallOutcomeRequest, CallOutcomeResponse,
    NextActionRequest, NextActionResponse,
)
from app.core.logging import get_logger

logger = get_logger(__name__)

# ── Mapping: Call Outcome → New Lead Status ──────────────────────
_OUTCOME_TO_STATUS: Dict[CallOutcome, str] = {
    CallOutcome.INTERESTED: LeadStatus.CONTACTED.value,
    CallOutcome.VERY_INTERESTED: LeadStatus.CONTACTED.value,
    CallOutcome.NEED_TIME: LeadStatus.CONTACTED.value,
    CallOutcome.CALL_LATER: LeadStatus.CONTACTED.value,
    CallOutcome.NO_ANSWER: LeadStatus.NEW.value,
    CallOutcome.WRONG_NUMBER: LeadStatus.ARCHIVED.value,
    CallOutcome.NOT_INTERESTED: LeadStatus.ARCHIVED.value,
    CallOutcome.ALREADY_REGISTERED: LeadStatus.PAID.value,
    CallOutcome.PAYMENT_PENDING: LeadStatus.CONFIRMED_UNPAID.value,
}

# ── Mapping: Call Outcome → Suggested Next Action ────────────────
_OUTCOME_TO_ACTION: Dict[CallOutcome, str] = {
    CallOutcome.INTERESTED: "Envoyer brochure par email + relancer dans 48h",
    CallOutcome.VERY_INTERESTED: "Planifier RDV immédiat + envoyer lien inscription",
    CallOutcome.NEED_TIME: "Relancer dans 5 jours avec email de rappel",
    CallOutcome.CALL_LATER: "Programmer un rappel dans 48h",
    CallOutcome.NO_ANSWER: "Réessayer demain matin entre 9h-11h",
    CallOutcome.WRONG_NUMBER: "Archiver le lead et notifier le manager",
    CallOutcome.NOT_INTERESTED: "Archiver + envoyer email de remerciement",
    CallOutcome.ALREADY_REGISTERED: "Confirmer l'inscription dans le système",
    CallOutcome.PAYMENT_PENDING: "Envoyer rappel de paiement dans 24h",
}

# ── Mapping: Call Outcome → Follow-up delay ─────────────────────
_OUTCOME_TO_FOLLOWUP_DAYS: Dict[CallOutcome, int] = {
    CallOutcome.INTERESTED: 2,
    CallOutcome.VERY_INTERESTED: 0,
    CallOutcome.NEED_TIME: 5,
    CallOutcome.CALL_LATER: 2,
    CallOutcome.NO_ANSWER: 1,
    CallOutcome.PAYMENT_PENDING: 1,
}


class SDRCopilotService:
    def __init__(self, repository: LeadRepository, llm_provider: LLMProvider, catalog_repo=None):
        self._repository = repository
        self._llm = llm_provider
        self._catalog_repo = catalog_repo

        data_dir = Path(__file__).parent.parent / "data"
        self._objections_content = self._load_file(data_dir / "objections.md")

    def _load_file(self, filepath: Path) -> str:
        try:
            return filepath.read_text(encoding="utf-8")
        except FileNotFoundError:
            logger.warning(f"{filepath.name} not found. SDR will run without context.")
            return f"No {filepath.name} available."

    def _extract_all_sections(self, text: str, keywords: list[str]) -> dict:
        """Extracts text for all sections robustly by finding keyword positions and slicing."""
        sections = {k: "" for k in keywords}
        positions = {}
        for keyword in keywords:
            match = re.search(r'\b' + keyword + r'\b', text, re.IGNORECASE)
            if match:
                positions[keyword] = match.end()

        sorted_pos = sorted(positions.items(), key=lambda x: x[1])

        for i, (keyword, start_idx) in enumerate(sorted_pos):
            start = start_idx
            while start < len(text) and text[start] in ('-', ':', '*', ' ', '\n', '#'):
                start += 1

            end_idx = sorted_pos[i + 1][1] - len(sorted_pos[i + 1][0]) if i + 1 < len(sorted_pos) else len(text)

            if i + 1 < len(sorted_pos):
                temp_end = end_idx
                while temp_end > start and text[temp_end - 1] in ('-', ':', '*', ' ', '\n', '#'):
                    temp_end -= 1
                end_idx = temp_end

            val = text[start:end_idx].strip()
            sections[keyword] = val if val else f"Section {keyword} vide."

        for keyword in keywords:
            if keyword not in positions:
                sections[keyword] = f"Section {keyword} non générée."

        return sections

    # ═══════════════════════════════════════════════════════════════
    # MODULE 1 — Generate Brief (Sprint 1)
    # ═══════════════════════════════════════════════════════════════

    def generate_brief(self, lead_id: str) -> SDRBriefResponse:
        lead = self._repository.get_lead_by_id(lead_id)
        if not lead:
            raise ValueError(f"Lead {lead_id} not found")

        system_prompt = (
            "Tu es l'assistant IA Copilote pour les commerciaux (SDR) de Net-Info (DigiArt). "
            "Ton rôle est de préparer le commercial AVANT l'appel.\n\n"
            "RÈGLES ABSOLUES :\n"
            "1. Tu ne dois JAMAIS inventer d'informations sur le prospect. Utilise UNIQUEMENT les données fournies ci-dessous.\n"
            "2. Si une information est manquante (vide ou None), dis-le clairement : 'Non renseigné'.\n"
            "3. N'invente JAMAIS de nom de commercial. Utilise [Votre Nom] comme placeholder.\n"
            "4. Utilise le nom RÉEL du prospect tel qu'il est fourni.\n"
            "5. Sois concis. Chaque section doit faire 3-5 lignes maximum (sauf OBJECTIONS : 2 objections max).\n\n"
            "FORMAT DE RÉPONSE (respecte EXACTEMENT ces délimiteurs) :\n"
            "---SUMMARY---\n(Résumé factuel du prospect basé UNIQUEMENT sur ses données)\n"
            "---PITCH---\n(Script d'accroche personnalisé de 3-4 phrases)\n"
            "---OBJECTIONS---\n(Les 2 objections les plus probables pour CE profil et comment y répondre)\n"
            "---EMAIL---\n(Brouillon d'email en TEXTE BRUT, SANS balises HTML, SANS Markdown)\n"
        )

        agenda_info = ""
        catalog_info = ""
        if self._catalog_repo:
            catalog_info = self._catalog_repo.get_catalog_content_text()
            if lead.training:
                agenda = self._catalog_repo.get_course_agenda(lead.training)
                if agenda:
                    agenda_info = f"\nAgenda pour {lead.training} : Prochaine session le {agenda.get('Next Session Date')}, {agenda.get('Available Seats')} places restantes. Format: {agenda.get('Format')}.\n"

        user_prompt = f"""
Voici le catalogue des formations de l'école :
{catalog_info}
{agenda_info}

Voici les consignes pour gérer les objections :
{self._objections_content}

---
DONNÉES RÉELLES DU PROSPECT (ne rien inventer au-delà de ces données) :
- Nom complet : {lead.fullname}
- Téléphone : {lead.phone or 'Non renseigné'}
- Email : {lead.email or 'Non renseigné'}
- Formation demandée : {lead.training or 'Non renseigné'}
- Source d'acquisition : {lead.source}
- Statut actuel : {lead.status}
- Score AI : {lead.score if lead.score is not None else 'Non calculé'}
- Priorité : {lead.priority if lead.priority else 'Non définie'}
- Notes existantes : {lead.notes or 'Aucune note'}
- Message du prospect : {lead.raw_message or lead.called_by or 'Aucun message'}
- Déjà contacté : {'Oui' if lead.called else 'Non'}
- Dernier contact : {lead.last_contact or 'Jamais contacté'}

Génère les 4 sections ---SUMMARY---, ---PITCH---, ---OBJECTIONS---, ---EMAIL---.
"""

        llm_response = self._llm.generate(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            max_tokens=1500
        )

        output_text = llm_response.text
        sections = self._extract_all_sections(output_text, ["SUMMARY", "PITCH", "OBJECTIONS", "EMAIL"])

        customer_summary = sections["SUMMARY"]
        suggested_pitch = sections["PITCH"]
        predicted_objections = sections["OBJECTIONS"]
        email_draft_html = sections["EMAIL"]

        lead.sdr_brief = f"PITCH:\n{suggested_pitch}\n\nOBJECTIONS:\n{predicted_objections}"
        lead.email_draft = email_draft_html
        self._repository.update_lead(lead)

        return SDRBriefResponse(
            lead_id=lead_id,
            fullname=lead.fullname,
            priority=lead.priority if lead.priority else "UNSCORED",
            customer_summary=customer_summary,
            suggested_pitch=suggested_pitch,
            predicted_objections=predicted_objections,
            email_draft_html=email_draft_html,
        )

    # ═══════════════════════════════════════════════════════════════
    # MODULE 3 — Objection Handler (Sprint 2)
    # ═══════════════════════════════════════════════════════════════

    def handle_objection(self, request: ObjectionRequest) -> ObjectionResponse:
        lead = self._repository.get_lead_by_id(request.lead_id)
        if not lead:
            raise ValueError(f"Lead {request.lead_id} not found")

        system_prompt = (
            "Tu es l'expert en gestion d'objections commerciales de Net-Info (DigiArt).\n"
            "Le commercial est EN APPEL avec un prospect qui vient de formuler une objection.\n\n"
            "RÈGLES :\n"
            "1. Identifie la CATÉGORIE de l'objection (prix, temps, décideur, distance, compétence, autre).\n"
            "2. Fournis une réponse PROFESSIONNELLE et EMPATHIQUE basée sur les consignes officielles.\n"
            "3. Propose une offre alternative si possible.\n"
            "4. Recommande l'action suivante.\n\n"
            "FORMAT (respecte ces délimiteurs) :\n"
            "---CATEGORIE---\n(prix/temps/decideur/distance/competence/autre)\n"
            "---REPONSE---\n(La réponse professionnelle à dire au client)\n"
            "---ALTERNATIVE---\n(Offre alternative à proposer)\n"
            "---ACTION---\n(Action suivante recommandée)\n"
        )

        catalog_info = self._catalog_repo.get_catalog_content_text() if self._catalog_repo else "Non disponible"
        user_prompt = f"""
Consignes officielles pour gérer les objections :
{self._objections_content}

Catalogue des formations :
{catalog_info}

---
Prospect : {lead.fullname}
Formation demandée : {lead.training or 'Non renseigné'}
Priorité : {lead.priority}

OBJECTION DU CLIENT (mot pour mot) :
"{request.objection_text}"

Réponds avec les 4 sections ---CATEGORIE---, ---REPONSE---, ---ALTERNATIVE---, ---ACTION---.
"""

        llm_response = self._llm.generate(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            max_tokens=600
        )

        sections = self._extract_all_sections(
            llm_response.text, ["CATEGORIE", "REPONSE", "ALTERNATIVE", "ACTION"]
        )

        return ObjectionResponse(
            lead_id=request.lead_id,
            objection_category=sections["CATEGORIE"],
            recommended_response=sections["REPONSE"],
            alternative_offer=sections["ALTERNATIVE"],
            suggested_next_action=sections["ACTION"],
        )

    # ═══════════════════════════════════════════════════════════════
    # MODULE 6 — Call Outcome Management (Sprint 2)
    # ═══════════════════════════════════════════════════════════════

    def process_call_outcome(self, request: CallOutcomeRequest) -> CallOutcomeResponse:
        lead = self._repository.get_lead_by_id(request.lead_id)
        if not lead:
            raise ValueError(f"Lead {request.lead_id} not found")

        # Parse string outcome safely
        raw_outcome_str = (request.outcome or "").lower().strip().replace(" ", "_")
        try:
            outcome = CallOutcome(raw_outcome_str)
        except ValueError:
            # Fallback if n8n sends something weird
            outcome = CallOutcome.INTERESTED

        new_status = _OUTCOME_TO_STATUS.get(outcome, LeadStatus.NEW.value)
        suggested_action = _OUTCOME_TO_ACTION.get(outcome, "Pas d'action recommandée")
        if lead.training:
            suggested_action = f"{suggested_action} pour '{lead.training}'"

        followup_days = _OUTCOME_TO_FOLLOWUP_DAYS.get(outcome)

        next_followup = None
        if followup_days is not None:
            # Use local time instead of UTC so that after midnight local time, the date is correct.
            next_followup = (datetime.now() + timedelta(days=followup_days)).strftime("%Y-%m-%d")

        # ── Agenda urgency override ──────────────────────────────
        # If the requested course starts very soon, override the generic action
        # with a specific urgent call-to-action based on the real session date.
        if self._catalog_repo and lead.training:
            agenda = self._catalog_repo.get_course_agenda(lead.training)
            if agenda and agenda.get("Next Session Date"):
                try:
                    session_date = datetime.strptime(
                        str(agenda["Next Session Date"]), "%Y-%m-%d"
                    ).date()
                    days_to_start = (session_date - datetime.now().date()).days
                    if 0 < days_to_start <= 7:
                        seats = agenda.get("Available Seats", "?")
                        fmt = agenda.get("Format", "")
                        suggested_action = (
                            f"RELANCE URGENTE — Session '{lead.training}' démarre dans "
                            f"{days_to_start} jours ({session_date}). "
                            f"{seats} place(s) restante(s). Format : {fmt}. Finaliser l'inscription aujourd'hui !"
                        )
                        # Override follow-up to tomorrow at the latest
                        next_followup = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
                except Exception:
                    pass

        agenda_info = ""
        if self._catalog_repo and lead.training:
            agenda = self._catalog_repo.get_course_agenda(lead.training)
            if agenda:
                agenda_info = f"\nAgenda pour {lead.training} : Prochaine session le {agenda.get('Next Session Date')}, {agenda.get('Available Seats')} places restantes. Format: {agenda.get('Format')}.\n"

        # Generate call summary and follow-up email via LLM
        system_prompt = (
            "Tu es un assistant IA strict. Ton rôle est de rédiger un compte rendu d'appel commercial.\n"
            "RÈGLES ABSOLUES :\n"
            "1. NE JAMAIS INVENTER de dates. Utilise EXACTEMENT les dates fournies.\n"
            "2. NE JAMAIS TRADUIRE les termes techniques (ex: garde 'Generative AI').\n"
            "3. Sois très précis et professionnel.\n\n"
            "FORMAT OBLIGATOIRE :\n"
            "---RESUME---\n(1 phrase factuelle sur l'intérêt du prospect)\n"
            "---FOLLOWUP_EMAIL---\n(Email professionnel et bien formaté en HTML. Utilise <p>, <br>, <strong> pour structurer. Mentionne la vraie date de session. Ne mets pas de Markdown de code autour de l'HTML.)\n"
        )

        user_prompt = f"""
DONNÉES DE L'APPEL :
- Prospect : {lead.fullname}
- Formation : {lead.training or 'Non renseigné'}
- Détails de la formation : {agenda_info or 'Non disponibles'}
- Résultat de l'appel : {outcome.value}
- Notes du commercial : {request.call_notes or 'Aucune note'}

Génère les 2 sections : ---RESUME--- et ---FOLLOWUP_EMAIL---.
"""

        llm_response = self._llm.generate(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            max_tokens=600,
            temperature=0.1
        )

        sections = self._extract_all_sections(
            llm_response.text, ["RESUME", "FOLLOWUP_EMAIL"]
        )

        # ── Update lead in repository ────────────────────────────
        lead.status = new_status
        lead.called = True
        lead.called_at = datetime.now(timezone.utc)
        lead.last_contact = datetime.now(timezone.utc)
        if request.call_notes:
            existing = lead.notes or ""
            timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
            lead.notes = f"{existing}\n[{timestamp}] Appel ({outcome.value}): {request.call_notes}".strip()
        lead.next_action = suggested_action
        lead.next_followup_date = next_followup
        self._repository.update_lead(lead)

        logger.info(
            f"Call outcome processed for {lead.fullname}: {outcome.value} → status={new_status}",
        )

        return CallOutcomeResponse(
            lead_id=request.lead_id,
            outcome=outcome.value,
            new_status=new_status,
            call_summary=sections["RESUME"],
            follow_up_email_draft=sections["FOLLOWUP_EMAIL"],
            suggested_next_action=suggested_action,
            next_followup_date=next_followup,
        )

    # ═══════════════════════════════════════════════════════════════
    # MODULE 5 — Next Best Action Engine (Sprint 2)
    # ═══════════════════════════════════════════════════════════════

    def recommend_next_action(self, lead_id: str) -> NextActionResponse:
        lead = self._repository.get_lead_by_id(lead_id)
        if not lead:
            raise ValueError(f"Lead {lead_id} not found")

        # ── Rule-based pre-analysis ──────────────────────────────
        priority = lead.priority or "unscored"
        score = lead.score
        status = lead.status
        called = lead.called
        last_contact = lead.last_contact

        # Simple heuristics first (business rules, no LLM needed)
        if status in (LeadStatus.ARCHIVED.value, LeadStatus.PAID.value):
            return NextActionResponse(
                lead_id=lead_id,
                recommended_action="aucune_action",
                reasoning=f"Lead archivé ou déjà payé (statut: {status}).",
                urgency="basse",
            )

        if priority == LeadPriority.P0.value and not called:
            return NextActionResponse(
                lead_id=lead_id,
                recommended_action="appeler_immediatement",
                reasoning=f"Lead P0 non encore contacté. Score: {score}. Chaque minute compte.",
                urgency="haute",
                message_template=f"Bonjour {lead.fullname}, je suis [Votre Nom] de Net-Info. Je vous contacte suite à votre demande concernant {lead.training or 'nos formations'}.",
            )

        if priority == LeadPriority.P1.value and not called:
            return NextActionResponse(
                lead_id=lead_id,
                recommended_action="appeler_dans_2h",
                reasoning=f"Lead P1 non contacté (score {score}). Priorité standard, appeler dans les 2 heures.",
                urgency="moyenne",
            )

        if called and last_contact:
            days_since = (datetime.now(timezone.utc) - last_contact).days
            if days_since >= 5:
                return NextActionResponse(
                    lead_id=lead_id,
                    recommended_action="relancer_par_email",
                    reasoning=f"Dernier contact il y a {days_since} jours. Relance nécessaire.",
                    urgency="moyenne",
                    message_template=f"Bonjour {lead.fullname}, nous revenons vers vous suite à notre échange. Avez-vous eu le temps de réfléchir à la formation {lead.training or 'proposée'} ?",
                )
            elif days_since >= 2:
                return NextActionResponse(
                    lead_id=lead_id,
                    recommended_action="envoyer_brochure",
                    reasoning=f"Dernier contact il y a {days_since} jours. Envoyer la brochure pour maintenir l'intérêt.",
                    urgency="basse",
                )

        agenda_info = ""
        if self._catalog_repo and lead.training:
            agenda = self._catalog_repo.get_course_agenda(lead.training)
            if agenda and agenda.get("Next Session Date"):
                try:
                    session_date = datetime.strptime(agenda["Next Session Date"], "%Y-%m-%d").date()
                    days_to_start = (session_date - datetime.now().date()).days
                    if days_to_start > 0 and days_to_start <= 7:
                        return NextActionResponse(
                            lead_id=lead_id,
                            recommended_action="relance_urgente_agenda",
                            reasoning=f"La session de {lead.training} commence dans {days_to_start} jours ! Urgence de closing.",
                            urgency="haute",
                            message_template=f"Bonjour {lead.fullname}, c'est le moment ! Votre formation démarre dans {days_to_start} jours, finalisons votre inscription."
                        )
                    agenda_info = f"Session {lead.training} démarre le {session_date} (dans {days_to_start} jours)."
                except Exception:
                    pass

        if status == LeadStatus.CONFIRMED_UNPAID.value:
            return NextActionResponse(
                lead_id=lead_id,
                recommended_action="rappel_paiement",
                reasoning="Le lead a confirmé son inscription mais n'a pas encore payé.",
                urgency="haute",
                message_template=f"Bonjour {lead.fullname}, nous vous rappelons que votre inscription à {lead.training or 'la formation'} est en attente de paiement.",
            )

        # Default: use LLM for complex cases
        system_prompt = (
            "Tu es le moteur de recommandation commerciale de Net-Info. "
            "Analyse le profil du lead et recommande UNE SEULE action. "
            "Réponds en 2 phrases maximum. Sois direct et actionnable."
        )
        user_prompt = f"""
Lead: {lead.fullname} | Priorité: {priority} | Score: {score} | Statut: {status}
Contacté: {'Oui' if called else 'Non'} | Formation: {lead.training or 'N/A'}
Agenda info: {agenda_info or 'N/A'}
Notes: {lead.notes or 'Aucune'}

Quelle est la meilleure action à prendre maintenant ?
"""
        llm_response = self._llm.generate(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            max_tokens=150
        )

        return NextActionResponse(
            lead_id=lead_id,
            recommended_action="action_llm",
            reasoning=llm_response.text,
            urgency="moyenne",
        )
