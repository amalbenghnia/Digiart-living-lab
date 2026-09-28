"""Prompts for the email generation service.

These prompts instruct the LLM to generate a ready-to-send email for
a lead. The LLM MUST return a strict JSON object so the service can
parse it reliably. No free-form output is allowed.
"""
from __future__ import annotations

from app.models.lead import Lead

PROMPT_VERSION = "email_v2"

EMAIL_SYSTEM_PROMPT = """Tu es l'assistant commercial de DigiArt / Net-Info, une école de formation en arts numériques, 3D et IA.
Tu rédiges des emails PROFESSIONNELS en FRANÇAIS uniquement.

RÈGLES STRICTES :
1. TOUJOURS utiliser le VRAI prénom fourni dans les données. NE JAMAIS écrire [Prospect's Name] ou [Nom].
2. Écrire UNIQUEMENT en français. Aucun mot en anglais sauf les noms de formations.
3. Le JSON doit être parsable directement par json.loads(). AUCUN bloc markdown (```), AUCUN texte avant ou après le JSON.
4. La valeur "body_html" doit contenir du HTML PUR et valide. Ne pas inclure de balises <html>, <head>, <body>.

FORMAT DE RÉPONSE (UNIQUEMENT CE JSON, RIEN D'AUTRE) :
{"subject": "...", "body_html": "...", "body_text": "..."}
"""


def build_contact_p1_prompt(lead: Lead) -> str:
    """First outreach email for a P1 lead not called within 24h."""
    notes_block = f"\nMessage original du prospect : \"{lead.raw_message}\"\n" if getattr(lead, 'raw_message', None) else ""
    first_name = lead.fullname.split()[0] if lead.fullname else "cher prospect"
    return f"""Génère un email de PREMIER CONTACT en français pour ce prospect.

DONNÉES RÉELLES DU PROSPECT :
- Prénom à utiliser dans l'email : {first_name}
- Nom complet : {lead.fullname}
- Formation d'intérêt : {lead.training or 'Nos formations'}
- Source : {lead.source}{notes_block}

OBJECTIF : Email chaleureux de premier contact. Ce prospect vient de manifester de l'intérêt.
- Saluer par son VRAI prénom ({first_name}), pas par [Prénom] ou [Nom]
- Mentionner la formation "{lead.training or 'nos formations'}" spécifiquement
- Proposer un appel de 15 minutes pour en discuter
- Donner un numéro ou email de contact fictif de DigiArt
- Signer "L'équipe DigiArt"

Le body_html doit utiliser <p>, <br>, <strong>, <ul><li> pour être lisible et élégant.
Exemple de structure attendue pour body_html :
"<p>Bonjour <strong>{first_name}</strong>,</p><p>Nous avons bien reçu votre intérêt pour <strong>{lead.training or 'nos formations'}</strong>...</p><p>...</p><p>Cordialement,<br><strong>L'équipe DigiArt</strong></p>"
"""


def build_nurturing_p2_prompt(lead: Lead) -> str:
    """Nurturing email for a P2 lead — informational, no hard sell."""
    first_name = lead.fullname.split()[0] if lead.fullname else "cher prospect"
    return f"""Génère un email de RELANCE INFORMATIONNELLE en français pour ce prospect.

DONNÉES RÉELLES DU PROSPECT :
- Prénom à utiliser : {first_name}
- Nom complet : {lead.fullname}
- Formation d'intérêt : {lead.training or 'Nos formations'}

OBJECTIF : Email informatif sans pression commerciale.
- Saluer par son VRAI prénom ({first_name})
- Partager 2-3 points forts de la formation "{lead.training or 'nos formations'}"
- Terminer par une question ouverte simple
- Signer "L'équipe DigiArt"

Le body_html doit utiliser <p>, <strong>, <ul><li> pour présenter les avantages sous forme de liste.
Exemple attendu : "<p>Bonjour <strong>{first_name}</strong>,</p>..."
"""


def build_payment_reminder_prompt(lead: Lead, days_overdue: int = 0) -> str:
    """Payment reminder for a confirmed but unpaid lead."""
    first_name = lead.fullname.split()[0] if lead.fullname else "cher prospect"
    delay_text = f"depuis {days_overdue} jour(s)" if days_overdue > 0 else "et reste en attente"
    return f"""Génère un email de RELANCE DE PAIEMENT poli mais ferme en français.

DONNÉES RÉELLES DU PROSPECT :
- Prénom à utiliser : {first_name}
- Nom complet : {lead.fullname}
- Formation confirmée : {lead.training or 'votre formation'}
- Statut : paiement en attente {delay_text}

OBJECTIF : Rappeler poliment que le paiement est attendu. Proposer de l'aide.
- Saluer par son VRAI prénom ({first_name})
- Mentionner la formation "{lead.training or 'la formation'}" par son vrai nom
- Ne jamais menacer. Rester compréhensif mais direct.
- Proposer un contact téléphonique ou email pour régler tout problème
- Signer "L'équipe DigiArt"

Le body_html doit utiliser <p>, <strong> pour les informations importantes.
"""
