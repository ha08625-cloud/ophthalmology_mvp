**V5.0:**
- Replace LLM driven RP with encoder driven RP system

**V6.0:**
- Add provenance and confidence (field level provenance and confidence tracking slots exist in state manager but not yet output by RP)
- Selective state injection
- Contradiction detection

**V7.0:**
- Expand system to extract shared fields with systems review, past medical history, medications, social history
- NOTE: systems review is a limited series of yes/no questions for symptoms relevant to neuro-ophthalmology, NOT a full expansion into the whole of the rest of general medicine
- Past medical history and medications will largely be sourced from the referal letter NOT from the patient during the consultation, just verified
- Allow integration of previous clinical records into the summary generator

**V8.0:**
- Create labelled validation set
- Error taxonomy + per-field metrics
- targeted adversarial tests to quantify the exact gap and ROI for fixes
- Confidence calibration
- Retry question logic

**V9.0:**
- Fine-Tuning
- Prepare training data with provenance
- Multiple fine-tuning experiments, trial different data augmentation methods, recombination strategies
- A/B testing different LoRA strategies:
- Individual LoRAs (response parser, summary generator and question naturaliser all run on same LoRA) vs specialised LoRAs (response parser, summary generator and question naturaliser trained using different fine tuning data)
- Chunked summarisation vs whole consultation summarisation, consider trialling and evaluating separately fine tuned LoRAs for ophthalmology specific summarisation vs general medical summarisation (systems review, PMH, medications etc)

**V10.0:**
- Time measurement: granularity (e.g. approximate month), confidence (e.g. certain or uncertain), relative time (2 months ago) vs absolute time (July 2025)
- Add temporal confidence follow up question: After patient responds "About 5 months ago", follow up with "How certain are you about that timeframe - very certain, somewhat certain, or just a rough guess?"
- How to handle time: about 2 months ago

**V11.0:**
- UX improvements:
- Question naturalizer using LLM, or
- Experiment with immediate verification via deterministic naturalizer: e.g. response parser returns right_eye, question selector selects vl_first_onset as next question, dialogue manager returns "Thank you, the vision loss was in your right eye.  When did it first start?" (All determinstically coded)
- Multi-turn clarification (ask follow ups when unclear)
- Visual aid tools to help describe visual fields and timelines

**V12.0:**
- Reconciliation workflow
- Coref resolver if necessary
- Web UI improvements
- Trialling with higher spec hardware e.g. cloud GPU.  Aim: speed up processing of response parser and question naturaliser (continue with small parameter models 7-8B) and improve summary generation (move to larger model 30-70B)
