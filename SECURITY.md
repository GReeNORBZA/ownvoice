# Security

ownvoice handles private mail, so its privacy controls are its security boundary. Please report privately, through GitHub's "Report a vulnerability" button on this repository's Security tab:

- a way for a person's name, address or other identifier to survive the scrub into a generated artefact or an LLM request;
- a way for a mailbox, export or generated artefact to get past `ownvoice guard` into a commit;
- text inside an email that can make the LLM skills act on it as an instruction;
- a generated file written with permissions wider than owner-only, or inside a git working tree.

Don't include real mail in a report. A synthetic message that reproduces the problem is enough. We aim to acknowledge reports within a week.
