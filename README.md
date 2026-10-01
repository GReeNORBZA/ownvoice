# ownvoice

Teach your AI agent to write emails and articles like you. ownvoice reads the email you've sent and works out how you actually write. Your agent then gets a profile of your voice and a checker that flags any draft that doesn't sound like you.

AI drafts are easy to spot, with the same tidy rhythm, the same stock phrases and a weakness for lists of three. Telling a model to "write like me" doesn't fix that, because it has no idea how you write. Your sent folder does. It shows how long your sentences run and how you sign off, that you talk to a client differently from a friend, and which words you'd never use.

## How it works

1. It opens your sent mail (Outlook PST, mbox or eml) and keeps only what you wrote, with quoted replies and signatures stripped out.
2. It masks names, addresses, phone numbers and sensitive terms.
3. It measures how you write for each kind of recipient, such as clients, colleagues and friends.
4. Your agent turns those numbers into a voice profile: an email voice for each kind of recipient, and a long-form voice for blog posts, LinkedIn, documents and proposals, built from your longer emails and, if you like, from how you revise your own drafts.
5. Every draft your agent writes goes through the checker, which flags anything that doesn't match you, including the usual AI habits, and the agent fixes it before you see it.

## Getting started

You don't need to be technical. Open your AI agent (Claude Code, Codex or similar) and paste this in:

> Install ownvoice from https://github.com/GReeNORBZA/ownvoice and set it up for me, following its docs/configuration.md. My sent mail is at [path]. Ask me before turning on anything that sends my email text to the AI model.

The agent installs it, asks a few questions (your email addresses, and which domains belong to clients) and builds your profile. Then ask it to "draft a reply to this in my voice" or "write a blog post about this in my voice". It needs Python 3.12 or newer. Outlook PST files need a free Linux reader, so on a Mac or Windows, export your Sent folder to mbox first.

## Getting the best out of it

- Give it plenty of mail. Years of sent mail beat months, and adding both your work and personal mailboxes means every kind of recipient gets a voice of its own.
- Set a cutoff date. If you've been writing with AI help for a while, tell it to ignore mail after you started (`baseline_before` in the config). Otherwise it learns the AI's habits back from your own outbox.
- Tell it who your clients are. Each recipient is sorted by email domain, so a few minutes mapping client, colleague and supplier domains makes the per-recipient voices much sharper.
- Allow scrubbed samples if you can. A statistics-only profile works, but one built from real sentences is a lot closer to you.
- Write down your rules: the words you hate and how formal you are. There's an example pack of common AI tells you can copy from.
- For articles, keep your drafts. If your drafts live in a folder or a git repository, it can compare each version with the last and learn how you edit.

## Your email stays yours

Everything runs on your own computer, and ownvoice itself never connects to the internet. By default your AI model only sees statistics about your writing, never the text. Letting it see scrubbed samples of your sentences gives a much better profile, but you'll be asked to record your AI provider's data terms first. The scrubbing isn't perfect, though; a name that only appears in the body of an email can slip through, so only switch this on for mail you're happy to share with your provider and have the right to use.

Every setting is in [docs/configuration.md](docs/configuration.md). Development notes are in [CONTRIBUTING.md](CONTRIBUTING.md), and [SECURITY.md](SECURITY.md) explains how to report a privacy problem. MIT licensed.
