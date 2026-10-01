# Editorial rules

This is an example rules file, not a template default. It ships a generic ban
pack for common AI-writing tells (Tier A of the AI-tells specification) so a
user can copy the entries they want into their own `ownvoice-rules` block. A
rules file holds exactly one machine block, so merge these entries into yours
rather than adding a second block. Every entry is generic English; nothing here
comes from any owner's corpus.

## Voice and register

- Tier A entries are lint errors. Each prints its location so a writer can
  judge the few medium false-positive patterns (joined negative parallelism,
  split-sentence reversal) and keep a genuine correction.
- Media: `email`, `article` and the other long-form media (`blog`, `linkedin`,
  `doc`, `proposal`). Entries marked long-form apply to articles only.
- Dashes: the em dash is banned in every medium. The spaced en dash (" – ") is
  allowed in email, where mail clients often convert a spaced hyphen, and is
  treated as an em dash in long-form media (`ait-a09-spaced-en-dash`). To ban it
  in email too, add `email` to that entry's media.
- Tricolons, hedge stacks, AI vocabulary density and the other threshold tells
  are not bans: `lint` warns on them from the user's own profile thresholds.
- Not expressible as a single pattern, so not shipped here: title-case
  headings, repeated labelled beats, short-sentence reveals and paired short
  contrasts.

## Publishing tiers

Not covered by this example.

## Open-source release gate

Not covered by this example.

## Images and diagrams

Not covered by this example.

## Process

Copy the entries you want, keep their ids unique in your file, and adjust
`media` and `severity` to taste. Rerun `ownvoice lint` to check a draft.

## Inferred, unconfirmed

Nothing inferred.

```ownvoice-rules
schema_version = 1

[[ban]]
id = "ait-a01-style-vocabulary"
kind = "regex"
pattern = '''\b(?:delve|delves|delved|delving|underscore|underscores|underscored|underscoring|showcase|showcases|showcased|showcasing|intricate|intricacies|meticulous|meticulously|commendable|tapestry|realm|garner|garnered|garnering|groundbreaking|pivotal|camaraderie|palpable|amidst|solace|testament|vibrant|beacon|interplay|bolstered|multifaceted|embark|embarks|embarking|unwavering|indelible|seamless|seamlessly|transformative|cutting-edge|paradigm|labyrinth|labyrinthine|kaleidoscope|symphony|mosaic|cornerstone|bedrock|odyssey|unleash|unleashing|elevate|elevating|empower|empowering|spearhead|resonates|resonated|noteworthy|illuminate|enigma|ever-evolving|interconnectedness|reverberate)\b'''
media = ["email", "article", "blog", "linkedin", "doc", "proposal"]
severity = "error"
message = "Replace AI-style vocabulary with a plain word (literal uses such as the underscore character are fine)."

[[ban]]
id = "ait-a02-participial-gloss"
kind = "regex"
pattern = ''',\s+(?:highlighting|underscoring|emphasi[sz]ing|showcasing|reflecting|demonstrating|illustrating|signal(?:l)?ing|solidifying|cementing|reinforcing|underlining|fostering|cultivating|encompassing|contributing to|aligning with|paving the way|setting the stage|marking)\b'''
media = ["email", "article", "blog", "linkedin", "doc", "proposal"]
severity = "error"
message = "Cut the trailing ', highlighting ...' gloss; state the point in its own sentence."

[[ban]]
id = "ait-a03-negative-parallelism"
kind = "regex"
pattern = '''\b(?:it|this|that|they|he|she|we)(?:['’]s|['’]re|\s+(?:is|was|are|were))\s+not\s+[^.!?\n,;—–]{1,60}[,;—–]\s*(?:it|this|that|they)(?:['’]s|['’]re|\s+(?:is|was|are|were))\b|\b(?:isn['’]t|aren['’]t|wasn['’]t|doesn['’]t)\s+(?:just\s+|about\s+)?[^.!?\n]{1,60}[,;—–]\s*(?:it|they|this|that)(?:['’]s|['’]re|\s+(?:is|are|was|does))\b|\bno\s+longer\s+(?:just|only|merely)?\s*[^.;:?!\n]{1,120}[.;:?!]\s*(?:it|they|you)\s+(?:is|are|was|were)\b'''
media = ["email", "article", "blog", "linkedin", "doc", "proposal"]
severity = "error"
message = "State what it is; drop the 'it isn't X, it's Y' frame."

[[ban]]
id = "ait-a04-correlative-inflation"
kind = "regex"
pattern = '''\bnot\s+(?:just|only|merely|simply)\s+[^.!?\n;]{1,80}?\bbut(?:\s+also)?\b|\b(?:isn['’]t|is not|aren['’]t|are not|wasn['’]t)\s+(?:just|merely|simply)\b'''
media = ["email", "article", "blog", "linkedin", "doc", "proposal"]
severity = "error"
message = "Drop 'not just X but Y'; say the larger claim directly."

[[ban]]
id = "ait-a05-significance-inflation"
kind = "regex"
pattern = '''\b(?:stands|serves) as a (?:testament|reminder)|\b(?:is|was|are) a testament to|\bplay(?:s|ed|ing)? an? (?:crucial|pivotal|vital|significant|key) role|\b(?:pivotal|key|crucial) (?:moment|turning point)|\bsetting the stage for|\bindelible mark|\bdeeply rooted|\bevolving landscape|\bever-(?:evolving|changing)|\breflects? (?:a )?broader|\bmarks? a (?:significant )?shift|\bfocal point|\b(?:underscores?|highlights?) (?:the|its) (?:importance|significance)|\b(?:serves|stands|functions) as (?:a|an|the)\b|\bholds the distinction of\b|\bboasts (?:a|an|the)\b'''
media = ["email", "article", "blog", "linkedin", "doc", "proposal"]
severity = "error"
message = "Cut the significance claim; use 'is' and the concrete fact."

[[ban]]
id = "ait-a05-this-highlights"
kind = "regex"
pattern = '''(?m)(?-i:(?:^|[.!?]\s+)(?:This|That|Which|It) (?:highlights|underscores|demonstrates|illustrates|speaks to|serves as)\b)'''
media = ["email", "article", "blog", "linkedin", "doc", "proposal"]
severity = "error"
message = "Do not explain what the previous sentence shows; the reader can see it."

[[ban]]
id = "ait-a06-reversal-copula"
kind = "regex"
pattern = '''\b(?:isn['’]t|is not|aren['’]t|are not)\s+[^.!?\n]{1,80}[.!?]\s+(?:it['’]s|it is|this['’]s|this is|that['’]s|that is|they['’]re|they are)\b'''
media = ["email", "article", "blog", "linkedin", "doc", "proposal"]
severity = "error"
message = "Split-sentence reversal ('It isn't X. It's Y.'); state the claim once."

[[ban]]
id = "ait-a06-reversal-have"
kind = "regex"
pattern = '''\b(you|we|they|i)\s+(?:don['’]t|do not|didn['’]t)\s+(have|need|want|get)\b[^.!?\n]{1,80}[.!?]\s+\1\s+\2\b'''
media = ["email", "article", "blog", "linkedin", "doc", "proposal"]
severity = "error"
message = "Split-sentence reversal ('You don't need X. You need Y.'); state the claim once."

[[ban]]
id = "ait-a06-reversal-the-real"
kind = "regex"
pattern = '''\bthe (\w+) (?:isn['’]t|is not|wasn['’]t)\b[^.!?\n]{1,80}[.!?]\s+the (?:real )?\1 (?:is|was)\b'''
media = ["email", "article", "blog", "linkedin", "doc", "proposal"]
severity = "error"
message = "Split-sentence reversal ('The problem isn't X. The real problem is Y.'); state it once."

[[ban]]
id = "ait-a06-reversal-means"
kind = "regex"
pattern = '''\b(?:this|that|it) (?:does not|doesn['’]t) mean\b[^.!?\n]{1,80}[.!?]\s+it means\b'''
media = ["email", "article", "blog", "linkedin", "doc", "proposal"]
severity = "error"
message = "Split-sentence reversal ('This doesn't mean X. It means Y.'); state it once."

[[ban]]
id = "ait-a07-chatbot-wrapper"
kind = "regex"
pattern = '''\bgreat question\b|\byou['’]re (?:absolutely|completely) right\b|\bis there anything else I can\b|\bshould I continue\b|\bwhat a (?:great|thoughtful|brilliant) (?:question|point|idea)\b|\b(?:excellent|fantastic|brilliant) (?:question|observation)\b|\bas an AI\b'''
media = ["email", "article", "blog", "linkedin", "doc", "proposal"]
severity = "error"
message = "Remove chatbot wrapper or flattery."

[[ban]]
id = "ait-a07-chat-residue-long-form"
kind = "regex"
pattern = '''\A\s*(?:Certainly|Absolutely|Of course|Sure)!|\A\s*(?:Below is|Here is a)\b|\bI hope this helps\b|\bwould you like me to\b|\bwant me to\b|\blet me know if you['’]d like\b'''
media = ["article", "blog", "linkedin", "doc", "proposal"]
severity = "error"
message = "Remove chat residue from long-form writing."

[[ban]]
id = "ait-a08-summary-signpost"
kind = "regex"
pattern = '''(?m)(?:^|[.!?]\s+)(?:in (?:summary|conclusion)|to (?:sum up|recap|summari[sz]e|conclude)|all in all|as we['’]ve seen)\b|\bwe['’]ve (?:explored|covered)\b|\bat the end of the day\b|^#{1,6}\s+(?:Conclusion|Summary|Key Takeaways|Final Thoughts|In Summary|Wrapping Up)\s*$'''
media = ["article", "blog", "linkedin", "doc", "proposal"]
severity = "error"
message = "End once, on new information; no recap signpost or 'Conclusion' heading."

[[ban]]
id = "ait-a09-em-dash"
kind = "char"
pattern = "—"
media = ["email", "article", "blog", "linkedin", "doc", "proposal"]
severity = "error"
message = "No em dashes; use a semicolon or split the sentence."

[[ban]]
id = "ait-a09-double-hyphen"
kind = "regex"
pattern = '''\s--\s'''
media = ["email", "article", "blog", "linkedin", "doc", "proposal"]
severity = "error"
message = "A spaced double hyphen is an em dash; use a semicolon or split the sentence."

[[ban]]
id = "ait-a09-spaced-en-dash"
kind = "regex"
pattern = '''\s–\s'''
media = ["article", "blog", "linkedin", "doc", "proposal"]
severity = "error"
message = "A spaced en dash reads as an em dash in long-form writing; use a semicolon (allowed in email)."

[[ban]]
id = "ait-a10-negation-countdown"
kind = "regex"
pattern = '''(?m)(?-i:(?:^|[.!?]\s+)Not\s+[^.!?\n]{1,40}\.\s+Not\s+[^.!?\n]{1,40}\.|(?:^|[.!?]\s+)No\s+\w+[^.!?\n]{0,30}[.,]\s+No\s+\w+[^.!?\n]{0,30}[.,]\s+(?:No|Just)\b)'''
media = ["email", "article", "blog", "linkedin", "doc", "proposal"]
severity = "error"
message = "Drop the 'Not X. Not Y. Just Z.' countdown."

[[ban]]
id = "ait-a11-throat-clearing"
kind = "regex"
pattern = '''\bin today['’]s (?:\w+ )?(?:world|age|era|landscape|environment|climate)\b|\bin an era (?:of|where)\b|\bin a world (?:where|of)\b|\bnow more than ever\b|\bin the (?:rapidly |ever-)(?:evolving|changing)\b|\bas the \w+ (?:continues to evolve|landscape evolves)|\bimagine (?:a world|a future)\b|\bwhether you['’]re (?:a|an)\b[^.\n]{1,60}\bor (?:a|an)\b'''
media = ["email", "article", "blog", "linkedin", "doc", "proposal"]
severity = "error"
message = "Cut the throat-clearing opener; start with the point."

[[ban]]
id = "ait-a12-pedagogical-run-up"
kind = "regex"
pattern = '''\blet['’]s (?:dive|delve|unpack|break (?:it|this) down|explore)\b|\bwithout further ado\b'''
media = ["email", "article", "blog", "linkedin", "doc", "proposal"]
severity = "error"
message = "Cut the run-up; start with the content."

[[ban]]
id = "ait-a13-false-suspense"
kind = "regex"
pattern = '''(?m)\bhere(?:['’]s|\s+is)\s+(?:the|a|my|one)\s+(?:twist|thing|catch|kicker|rub|deal|surprising|interesting|uncomfortable|truth)\b|\bhere['’]s (?:where it gets|what most people|what nobody|what no one|what you need to know)\b|(?:^|[.!?]\s+)the thing is\b'''
media = ["email", "article", "blog", "linkedin", "doc", "proposal"]
severity = "error"
message = "No staged suspense; put the point first."

[[ban]]
id = "ait-a14-self-posed-question"
kind = "regex"
pattern = '''(?m)(?:^|[.!?]\s+)(?:(?:And|But|So) )?(?:the )?(?:result|goal|catch|kicker|good news|bad news|worst part|best part|answer|problem|twist|reason|verdict|upshot|takeaway|point|fix|cost)\?\s+\S|\bHonestly\?\s'''
media = ["email", "article", "blog", "linkedin", "doc", "proposal"]
severity = "error"
message = "Do not pose a question and answer it at once; state the answer."

[[ban]]
id = "ait-a15-worth-noting"
kind = "regex"
pattern = '''\bit['’]s worth (?:noting|mentioning|pointing out)\b|\bit is worth (?:noting|mentioning|pointing out)\b|\bit(?:['’]s| is) (?:important|crucial|critical|essential) to (?:note|remember|consider|understand)\b|\bit should be noted\b|\bit bears mentioning\b|\bneedless to say\b|\bit goes without saying\b'''
media = ["email", "article", "blog", "linkedin", "doc", "proposal"]
severity = "error"
message = "Cut the filler; say the thing."

[[ban]]
id = "ait-a16-promotional"
kind = "regex"
pattern = '''\bnestled\b|\bin the heart of\b|\brich\s+(?:cultural\s+|historical\s+)?(?:heritage|history|tapestry)\b|\bhidden\s+gem\b|\bmust-(?:visit|see|try)\b|\bbreathtaking\b|\bstunning\s+(?:views?|scenery|architecture|backdrop)\b|\brevolutioni[sz]e\w*|\bsupercharge\w*|\bfuture-proof\w*|\bunlock the (?:power|potential|secrets?)\b|\bahead of the curve\b|\b(?:thrilled|excited) to announce\b|\bdiverse array\b|\brenowned\b|\bgame[- ]changer\b'''
media = ["email", "article", "blog", "linkedin", "doc", "proposal"]
severity = "error"
message = "Replace brochure language with the specific fact."

[[ban]]
id = "ait-a17-authority-trope"
kind = "regex"
pattern = '''\bthe real (?:question|story|issue|problem|unlock|lesson) is\b|\bat (?:its|the) core\b|\bmake no mistake\b|\bwhat really matters\b|\bthe heart of the matter\b|\bthe deeper (?:issue|problem|question)\b|\blies somewhere in between\b|\bthe (?:truth|reality) is\b'''
media = ["email", "article", "blog", "linkedin", "doc", "proposal"]
severity = "error"
message = "Drop the persuasive-authority frame; state the claim."

[[ban]]
id = "ait-a18-announced-candour"
kind = "regex"
pattern = '''\bworth (?:saying|stating|putting) (?:plainly|bluntly|directly|clearly|honestly)\b|\bsay(?:ing)? it plainly\b|\blet me be (?:clear|honest|blunt|frank|direct)\b|\bI['’]ll be (?:honest|blunt|frank|direct|clear)\b|\blet['’]s be (?:honest|clear|real|blunt)\b|\bI (?:will not|won['’]t) pretend\b|\breal talk\b|\bto be (?:fully |completely )?(?:transparent|upfront)\b|\bI want to be upfront\b|\bquite frankly\b|\btruth be told\b|\bto be (?:honest|clear|frank|blunt)\b'''
media = ["email", "article", "blog", "linkedin", "doc", "proposal"]
severity = "error"
message = "Never announce candour; write the direct sentence."

[[ban]]
id = "ait-a18-candour-adverb"
kind = "regex"
pattern = '''(?m)(?-i:(?:^|[.!?]\s+)(?:Honestly|Frankly|Truthfully),)'''
media = ["email", "article", "blog", "linkedin", "doc", "proposal"]
severity = "error"
message = "Never announce candour; write the direct sentence."

[[ban]]
id = "ait-a19-vague-attribution"
kind = "regex"
pattern = '''\b(?:experts|observers|critics|analysts|commentators) (?:argue|say|suggest|note|believe|have (?:cited|noted))\b|\bindustry reports (?:suggest|show)\b|\bseveral (?:sources|publications)\b|\bsome (?:might|may|would) (?:say|argue)\b'''
media = ["email", "article", "blog", "linkedin", "doc", "proposal"]
severity = "error"
message = "Name the source instead of a vague attribution."

[[ban]]
id = "ait-a20-despite-challenges"
kind = "regex"
pattern = '''\bdespite (?:these|its|their|the) (?:challenges|obstacles|setbacks|limitations)\b|\bfaces? (?:several|many|numerous) challenges\b'''
media = ["email", "article", "blog", "linkedin", "doc", "proposal"]
severity = "error"
message = "Name the actual problem instead of the 'despite its challenges' formula."

[[ban]]
id = "ait-a21-placeholder-residue"
kind = "regex"
pattern = '''\{[a-z_ ]+\}|\[(?:Your|Insert|Company)[^\]]*\]|contentReference|oaicite|turn0(?:search|news|image)\d*|utm_source=chatgpt|\bas of my last (?:knowledge )?(?:update|training)\b|\bknowledge cut-?off\b|\bwhile specific details are limited\b|\bbased on available information\b'''
media = ["email", "article", "blog", "linkedin", "doc", "proposal"]
severity = "error"
message = "Remove placeholder, markup leak or knowledge-cutoff residue."

[[ban]]
id = "ait-a22-formulaic-opener"
kind = "regex"
pattern = '''\b(?:hope|trust) (?:this|the|my) (?:e-?mail|message|note|mail) finds you\b|\bI am writing to (?:express|inquire|enquire)\b|\bI recently had the pleasure of\b'''
media = ["email", "article", "blog", "linkedin", "doc", "proposal"]
severity = "error"
message = "Drop the formulaic opener; start with the reason for writing."

[[ban]]
id = "ait-a24-emoji-formatting"
kind = "regex"
pattern = '''(?m)^(?:#{1,6}[ \t]+[^\n]*|\s*(?:[-*•]|\d+[.)])\s+|)[\U0001F300-\U0001FAFF☀-➿⭐✅]'''
media = ["article", "blog", "linkedin", "doc", "proposal"]
severity = "error"
message = "No emoji as headings, bullets or paragraph openers in long-form writing."

[[ban]]
id = "ait-a25-stock-pivot"
kind = "regex"
pattern = '''\bnot all bad news\b|\bhere['’]s the other side\b|\bthere['’]s (?:still )?hope\b|\bsilver lining\b|\bon a (?:brighter|positive|lighter) note\b|\bthe future (?:is|looks) bright\b|\bbut there['’]s a catch\b|\bthat being said\b|\bwhich raises (?:an|the) (?:uncomfortable|important|obvious)\b|\bbut here['’]s where it gets\b|\bthe good news is\b|\bbuilding on this\b'''
media = ["email", "article", "blog", "linkedin", "doc", "proposal"]
severity = "error"
message = "Move on by naming the next subject, not with a stock pivot."

[[ban]]
id = "ait-a26-colon-reveal"
kind = "regex"
pattern = '''(?m)\bthe (?:rule|point|answer|solution|lesson|problem|catch|truth|reality|takeaway|fix|trick|result|goal|reason|upshot|bottom line) is (?:this|simple|clear|straightforward)\s*:|\bthe (?:message|verdict) was clear\s*:|(?:^|[.!?]\s+)(?:the )?(?:tell|catch|kicker|twist|takeaway|upshot|bottom line|short version|point)\s*:|\bhere(?:['’]s| is) the (?:rule|point|thing|catch|kicker|lesson|truth|takeaway|problem|answer|twist|upshot|bottom line)\s*:'''
media = ["email", "article", "blog", "linkedin", "doc", "proposal"]
severity = "error"
message = "No colon reveal; put the point first."

[[ban]]
id = "ait-a27-performed-hesitancy"
kind = "regex"
pattern = '''\bdeeply nuanced\b|\bno easy answers?\b|\bit depends on how (?:one|you) define\b|\bfrom a certain perspective\b|\bmultifaceted\b|\bit['’]s complicated\b'''
media = ["email", "article", "blog", "linkedin", "doc", "proposal"]
severity = "error"
message = "Commit to a position or name the specific unknown."

[[ban]]
id = "ait-a28-performed-insight"
kind = "regex"
pattern = '''(?m)\b(?:that|this)(?:['’]s|\s+(?:is|was))\s+the\s+whole\s+(?:point|thing|story)\b|\b(?:that|this|it)(?:['’]s|\s+(?:is|was))\s+the\s+part\s+(?:nobody|no one)\b|(?:^|[.!?]\s+)turns\s+out\b|\bsit(?:s|ting)?\s+with\s+(?:that|this)\b|\bworth naming\b|\bthat['’]s not nothing\b|\bdon['’]t take my word for it\b|\bthe punchline is\b|\blet that sink in\b|\bread that again\b|(?:^|[.!?]\s+)full stop\.|\bthat distinction matters\b|\bthat is the real win\b|\b(?:that|this|the (?:last|first|second|third))\s+(?:\w+\s+)?(?:is|was)\s+the\s+(?:contrarian|clever|surprising|counterintuitive|interesting|real|actual)\s+(?:one|part|bit|story)\b'''
media = ["email", "article", "blog", "linkedin", "doc", "proposal"]
severity = "error"
message = "Cut the self-labelled insight; let the fact stand."

[[ban]]
id = "ait-a28-call-it"
kind = "regex"
pattern = '''\b(?:do\s+not|don['’]t)\s+(?:just\s+|simply\s+|merely\s+)?(\w+)(?:\s+(?:of|about|at|on|for|with|to))?\s+it\b[^.!?\n]*?[.!?;,:–—]\s*(?:just\s+|simply\s+|merely\s+)?\1(?:\s+(?:of|about|at|on|for|with|to))?\s+it\b'''
media = ["email", "article", "blog", "linkedin", "doc", "proposal"]
severity = "error"
message = "Drop the 'Don't call it X. Call it Y.' reframe."

[[ban]]
id = "ait-a29-stock-metaphor"
kind = "regex"
pattern = '''\bdouble-edged sword\b|\btip of the iceberg\b|\bnorth star\b|\belephant in the room\b|\bperfect storm\b|\bswiss army knife\b'''
media = ["email", "article", "blog", "linkedin", "doc", "proposal"]
severity = "error"
message = "Replace the stock metaphor with the literal point."

[[ban]]
id = "ait-a30-quietly"
kind = "regex"
pattern = '''\bquietly\b|\ba quiet (?:revolution|confidence|intelligence|shift|power|strength|dignity|force|kind of)\b|\bthe quiet part\b'''
media = ["email", "article", "blog", "linkedin", "doc", "proposal"]
severity = "error"
message = "Use 'quiet' only for sound or activity level."

[[ban]]
id = "ait-a34-coined-label"
kind = "regex"
pattern = '''\bthe \w+ (?:paradox|trap|creep|divide|vacuum|inversion|spiral|tax)\b'''
media = ["email", "article", "blog", "linkedin", "doc", "proposal"]
severity = "error"
message = "Describe the thing plainly instead of coining a label (established terms are fine)."

[[ban]]
id = "ait-a35-invented-aside"
kind = "regex"
pattern = '''\bI['’]ll (?:admit|confess)\b|\bguilty as charged\b|\bI['’]m no \w+,? but\b|\bconfession:|\bI['’]m (?:not )?(?:ashamed|embarrassed) to (?:admit|say)\b'''
media = ["email", "article", "blog", "linkedin", "doc", "proposal"]
severity = "error"
message = "Do not invent an aside; keep only one the brief supplied."
```
