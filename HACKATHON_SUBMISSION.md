# UT-Glasses: Real-Time Sign Language Translation Wearable

## Inspiration
Communication should never be a privilege.  
Millions of Deaf and hard-of-hearing people still face friction in daily conversations when people around them do not understand sign language. We wanted to build something practical, immediate, and human-centered: a wearable system that helps bridge that gap in real time.

That idea became **UT-Glasses**.

## What It Does
**UT-Glasses** captures sign gestures through a front-facing camera and translates them into readable text on a live companion interface.

Key capabilities:
- Real-time translation with low perceived latency
- Wearable + portable hardware setup
- Accessibility-first interaction for both signers and non-signers
- Modular architecture designed to expand to more signs and languages

## How We Built It
We combined computer vision, machine learning, embedded hardware, and realtime app engineering into one end-to-end pipeline.

Core build steps:
- Trained a gesture-recognition model on a curated sign-language dataset
- Integrated a camera module with a microcontroller-based streaming setup
- Built a realtime companion interface to display translated text instantly
- Designed a clean, high-contrast UI focused on readability and accessibility
- Connected hardware, backend inference, and frontend delivery in a live streaming loop

## Challenges We Ran Into
Shipping realtime translation on wearable constraints pushed us hard:

- Lighting shifts reduced detection consistency
- Tight model-size limits forced aggressive optimization
- Similar signs sometimes produced misclassifications
- Latency had to stay extremely low to feel conversational
- Hardware integration required careful tuning of camera behavior, reliability, and power usage

Each challenge forced rapid iteration across model design, pipeline logic, and system architecture.

## Accomplishments We’re Proud Of
- Delivered a working end-to-end prototype that captures, processes, and translates sign gestures live
- Reached low-latency inference performance suitable for natural conversation flow
- Applied model optimization strategies to keep the system lightweight while preserving useful accuracy
- Built an accessible companion UI that displays captions clearly and immediately
- Integrated hardware + software into one cohesive realtime product experience
- Designed the system to scale for broader vocabularies and multilingual support

## What We Learned
This project sharpened our skills in:
- Realtime computer vision pipelines
- Model optimization under edge constraints
- Embedded streaming and systems integration
- Accessibility-first product design

Most importantly, we learned that inclusive technology has its greatest impact when built with empathy, speed, and real-world usability in mind.

## What’s Next for UT-Glasses
- Expand the sign dataset and phrase coverage
- Improve robustness for complex and fast gestures
- Add support for additional sign languages
- Move toward a fully standalone wearable form factor
- Display translations directly on-lens
- Finalize cleaner hardware packaging with hidden wiring

---

**UT-Glasses** is our step toward making communication more universal, more immediate, and more human.
