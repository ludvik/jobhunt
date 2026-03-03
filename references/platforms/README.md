# Platform Knowledge Files

This directory contains platform-specific notes for ATS and job application systems encountered during automated job applications.

## Purpose

Each file documents quirks, working automation patterns, and gotchas for a specific platform. The apply agent reads the relevant file at the start of each application session and appends new findings after completion.

## File Naming

Files are named by platform/domain: `<platform-name>.md` (e.g., `greenhouse.md`, `workday.md`, `linkedin-easy.md`).

## How They're Updated

The apply agent (`agents/apply/task_prompt.md`) includes a **Reflect** step at the end of every application session. When new patterns are discovered:
1. The agent appends timestamped observations to the relevant platform file
2. If no file exists for the platform, the agent creates one
3. Only NEW insights are added — existing documentation is not repeated

## Format

Each entry should include:
- Date and job reference (e.g., `## 2026-03-01 observations (Job 83 - Okta)`)
- What was observed or tried
- What worked (actionable pattern)
- What failed (to avoid repeating mistakes)

## Usage by Apply Agent

At the start of each apply session, the agent reads the platform file for the target ATS (if known) to skip re-discovery and use documented working patterns directly.
