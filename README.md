# 🚀 DigiArt AI Management Hub

![DigiArt AI](https://img.shields.io/badge/AI-Multi--Agent_System-blue?style=for-the-badge)
![FastAPI](https://img.shields.io/badge/FastAPI-Backend-teal?style=for-the-badge)
![Ollama](https://img.shields.io/badge/Ollama-Local_LLMs-black?style=for-the-badge)
![n8n](https://img.shields.io/badge/n8n-Workflow_Automation-orange?style=for-the-badge)

The **DigiArt AI Management Hub** is an advanced, privacy-first **Multi-Agent System** designed to revolutionize the lead lifecycle and augment Sales Development Representatives (SDRs) at the DigiArt Living Lab. 

By combining the reasoning power of local Large Language Models (LLMs) with robust workflow automation, this system ensures zero leads are lost, response times are slashed, and every sales call is highly personalized.

---

## 🌟 The Vision & Value Proposition

In the competitive educational sector, speed and personalization are critical. When a prospective student expresses interest in a training program (e.g., Unity, XR, AI), a generic response often leads to drop-offs. 

**This project solves 3 major business challenges:**
1. **SLA Breaches:** Ensures high-priority (P0) leads are contacted within 2 hours.
2. **Context Switching:** Prevents SDRs from wasting time researching programs and market trends before a call.
3. **Data Privacy:** Runs 100% locally via Ollama, ensuring sensitive student data is never sent to external cloud APIs (like OpenAI).

---

## 🤖 The Multi-Agent Ecosystem

The system's core strength lies in its specialized AI agents. Rather than a single monolithic prompt, the workload is divided among expert agents, each with a distinct mission.

### 1. 🕵️ Lead Intake & Triage Agent
* **Mission:** Instantly process incoming raw leads from Meta Ads, web forms, or emails.
* **Concept:** It acts as the gatekeeper. It parses the lead's input, normalizes the data, detects potential duplicates in the database, and calculates a **Lead Score (0-100)**.
* **Action:** It assigns a strict Priority level (P0 = Hot/Urgent, P1 = Warm, P2 = Cold) determining how fast the human SDR needs to react.

### 2. 🎯 Course Recommendation Agent
* **Mission:** Match the prospective student with the perfect DigiArt curriculum.
* **Concept:** It analyzes the user's background, goals, and implicit desires against DigiArt's course catalog. 
* **Action:** It selects the most relevant training (e.g., *Interactive Systems Development*) and highlights exactly *why* this course fits the student's profile.

### 3. 📊 Market Intelligence Agent
* **Mission:** Provide data-backed sales arguments to the SDR.
* **Concept:** It bridges the gap between education and employment. It analyzes current market trends, job demand, and salary expectations for the targeted field.
* **Action:** It arms the SDR with concrete evidence ("The XR market is growing by 40% YoY, and Unity developers are in high demand in our region"), making the sales pitch highly persuasive.

### 4. 🧠 SDR Copilot Agent (Pre-Call Briefing)
* **Mission:** Eliminate pre-call preparation time for the sales team.
* **Concept:** It synthesizes the outputs of the Triage, Recommendation, and Intelligence agents into a single, digestible 1-minute brief.
* **Action:** Just before the SDR picks up the phone, they receive a brief containing: the lead's profile, the recommended pitch, potential objections the student might raise (e.g., "It's too expensive"), and exact counter-arguments.

### 5. ⏱️ The Watchdog (n8n Orchestrator)
* **Mission:** Enforce business rules and SLAs relentlessly.
* **Concept:** While the AI agents handle reasoning, the n8n automation engine acts as the heartbeat of the system.
* **Action:** It runs predefined workflows—such as scanning the database every 30 minutes for P0 leads that haven't been called, and firing urgent email alerts to the management team.

---

## 🏗️ Technical Architecture

The architecture is highly modular and fully containerized via **Docker**.

1. **The Brain (FastAPI):** A high-performance Python backend that orchestrates the AI agents, handles business logic, and interacts with the database (currently Google Sheets, migrating to PostgreSQL).
2. **The LLM Engine (Ollama):** Hosts open-source models (like Qwen2.5) directly on the local machine. This guarantees zero latency network overhead and absolute data sovereignty.
3. **The Nervous System (n8n):** 16 dynamic workflows (stored as JSON) that handle webhooks, crons, and third-party integrations (Gmail, Meta).

---

## 🚀 Quick Start (For Developers)

The entire stack is containerized. No manual installation of Python or Node.js is required.

1. **Clone the repository:**
   ```bash
   git clone <your-repo-url>
   cd lead_agent
   ```

2. **Configure Environments:**
   Copy the example environment file and fill in your keys.
   ```bash
   cp .env.example .env
   ```
   *Note: Place your Google Service Account JSON in `credentials/service_account.json` (this folder is git-ignored for security).*

3. **Start the Stack:**
   ```bash
   docker compose up -d
   ```

4. **Access the Services:**
   * **FastAPI Docs:** [http://localhost:8000/docs](http://localhost:8000/docs)
   * **SDR Dashboard:** [http://localhost:8000/hub](http://localhost:8000/hub)
   * **n8n Interface:** [http://localhost:5678](http://localhost:5678)

## 🛡️ Security & Privacy Notice

This repository is configured to be safely pushed to GitHub. The `.gitignore` file strictly prevents sensitive data from being uploaded. All environment variables, Google credentials, and local database files remain private to your local deployment.

## 🤝 Integration with Legacy Task Manager

Please refer to [`INTEGRATION_GUIDE_ENCADRANT.md`](./INTEGRATION_GUIDE_ENCADRANT.md) for full API contracts, Webhook payloads, and callback mechanisms required to connect the DigiArt AI Hub with the original Task Manager application.
