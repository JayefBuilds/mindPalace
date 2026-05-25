# Mind Palace — Talk Script
**Internal Company Talk | June 9, 2026 | 15–18 min**

---

## Slide 1 — Title
**Visual:** Exterior of a grand palace at dusk, dramatic and cinematic. Text: "Mind Palace" in elegant serif font, small subtitle: "Building Persistent Memory for AI Agents"

**Say:**
> "This is Mind Palace. Not the project — the concept. If you've watched the BBC Sherlock, you know the Mind Palace: a memory technique where you store information inside an imaginary place you can walk through and retrieve at will. That's the metaphor I kept coming back to as I was building this. So today, we're going to take a walk."

---

## Slide 2 — The Gate
**Visual:** Iron gate in the foreground, palace visible in the background through the bars. Closed. Slightly ominous.

**Say:**
> "Here's the problem. Every time you start a new session with an AI agent — Claude, Codex, doesn't matter — it wakes up with complete amnesia. It doesn't know what you built last week. It doesn't know the decision you made on Tuesday. It doesn't know *why* the code looks the way it does. You're standing outside the gate, and the palace is empty."

> "Now — to be fair — models have gotten better. Context windows are huge. Some agents can look at your whole codebase in one shot. That's real progress. But persistent memory — something that survives session boundaries, that builds up over time, that knows you and your project — that's still not a solved problem out of the box."

> "So I decided to solve it."

---

## Slide 3 — What I Actually Needed
**Visual:** Inside the foyer of the palace. Grand entrance, chandelier, two hallways branching off. Clean and organized.

**Say:**
> "When I started thinking about what I actually needed, it came down to a few things. I wanted an AI partner that remembered the *why* behind decisions. Not just what code exists, but why we made a call six weeks ago. I wanted it to flag things we might have forgotten. And I wanted it to feel less like a tool and more like a collaborator who had been there the whole time."

> "Think of the foyer as the moment you walk in and the palace actually recognizes you."

---

## Slide 4 — What Was Already Out There
**Visual:** A hallway with doors labeled: "Markdown Files," "Graph-Only Tools," "Semantic File Search." Each door slightly ajar, slightly disappointing.

**Say:**
> "Before building anything, I looked at what existed. The obvious option is just writing markdown files — a DECISIONS.md, a context doc. But that's entirely manual. You have to remember to write it, remember to read it, and it gets stale fast. Nobody actually keeps those up to date."

> "There were open source projects — some were graph-only, mapping entities and relationships in your code. Useful for some things, but not for *you*. Not for your preferences, your thinking, your history. Others were semantic search over files — basically grep with embeddings. Still no persistence across sessions."

> "None of them felt right. They were pieces, not a system."

---

## Slide 5 — So I Decided to Build It
**Visual:** A single candle-lit writing desk. A blank sheet of parchment, quill resting on it, the first line just begun. Warm amber light, rest of the room in shadow. A quiet moment of decision.

**Say:**
> "So I decided to build it. And I want to be honest about how that process went — because it's actually part of the story."

> "I didn't sit down with an architecture doc and execute it. I opened a conversation with Claude, shared a rough V1 spec I'd been thinking about, and we spent a session tearing it apart. What extraction model? What happens when memories contradict each other? How does retrieval stay fast when you have thousands of shards? One question led to the next. By the end of it we had a complete design — not an MVP, a complete design. The first commit had everything."

> "There's something a little meta about that. Using an AI to design an AI memory system. But that's also the point — this is what good collaboration with these tools actually looks like."

---

## Slide 6 — Building the Stack
**Visual:** A blueprint or architectural floor plan of the palace interior. Labeled rooms: Qdrant, Neo4j, Ollama, Claude Haiku. Arrows showing flow between rooms.

**Say:**
> "So we built one. I say 'we' because the research process itself was collaborative — me and Claude, spending a session in February stress-testing a V1 spec, looking at what was bleeding edge, what actually holds up. There's something a little meta about using an AI to design an AI memory system. And what came out of that session wasn't an MVP — the first commit landed with the full stack already complete."

> "The stack: Qdrant for vector search — that's semantic similarity, finding memories that *mean* something related to your query. Neo4j for graph memory — entity and relationship extraction, so the system understands that 'the auth refactor' is connected to 'the compliance requirement.' Ollama for local embeddings — completely free, runs on your machine, no API cost. And Claude Haiku for the smart parts: extracting memories from conversations, typing them, rewriting queries."

> "The retrieval pipeline has nine steps. Your query gets rewritten into two or three variants by a local LLM. Each variant searches both the vector store and the graph. Duplicates get deduplicated. Inactive memories get filtered. A cross-encoder reranker — running locally — scores the survivors by actual relevance. Then decay scoring weighs recency and how often a memory has actually been useful. The top results come back. The whole thing costs roughly a penny per session."

---

## Slide 7 — Memory Types
**Visual:** Five labeled shelves or drawers in a library room of the palace. Labels: Preference, Durable Fact, Decision, Open Loop, Correction.

**Say:**
> "One thing that makes this feel like a real memory system rather than a blob of text: typed memories. Every memory gets classified into one of five types. Preferences — how you like to work. Durable facts — things that are just true about your project. Decisions — choices you made and why. Open loops — things that are unresolved, things to come back to. Corrections — times you told the agent it was wrong."

> "That typing matters because it changes how the system retrieves and surfaces things. A correction is treated differently than a preference. And each type ages differently — a durable fact decays slowly, an open loop fades faster. Memories don't just get remembered; they get archived or pruned based on type and age."

---

## Slide 8 — The Problem With Manual
**Visual:** Someone standing in the palace shouting into a hallway. Nobody there.

**Say:**
> "For a while, this all worked — but it was still manual. I'd have to say 'save that to memory.' I'd have to say 'check your memory before we start.' If I forgot, the context didn't flow. It was only as good as my discipline, and honestly, my discipline is not always great at 11pm."

> "That friction was the next thing to fix."

---

## Slide 9 — The Hook System
**Visual:** A door in the palace with a mechanism — gears, a latch — that opens automatically when someone approaches. Screenshot of the hook firing in a Claude Code session, injecting memory context.

**Say:**
> "The solution was hooks. Claude Code and Codex both have a hook system — shell scripts that fire on agent lifecycle events. We wired Mind Palace into two of them."

> "On every prompt, before Claude even starts thinking: the hook fires, figures out which project you're in, redacts any secrets, skips trivial messages — 'ok', 'thanks', that kind of thing — then checks a 90-second cache. If it's a miss, it searches memory and injects relevant context silently. You don't ask. It just happens."

> "At the end of a session, the hook doesn't blindly save everything. It checks whether the conversation contained durable signal words — 'I prefer,' 'we decided,' 'remember.' Only if those signals are present does it queue an extraction job. Claude Haiku reads the conversation, pulls out the memories, types them, stores them. The queue is SQLite. The worker spawns as a background subprocess. Zero friction."

> "The palace now opens itself when you walk up to it."

---

## Slide 10 — Real Impact
**Visual:** A warm, lit study room in the palace. Books on shelves, a desk, a sense of accumulated work. Something personal and lived-in.

**Say:**
> "The moment this stopped feeling like an engineering project and started feeling like something real: I was working on my talk-to-text app — OTO — late one night. I'd been building it for months. Claude came into the session and immediately referenced a design decision we'd made six weeks earlier, explained why we'd ruled out a different approach, and flagged a dependency we hadn't revisited since. I hadn't asked. It just remembered."

> "That's the thing. It's not just about not repeating yourself. It's about having a partner who was there. Who holds the context you don't have bandwidth to hold."

---

## Slide 11 — What I'd Change
**Visual:** An unfinished wing of the palace — scaffolding, exposed walls, clearly in progress.

**Say:**
> "Honest takes: the graph layer with Neo4j adds complexity and doesn't always pay off. For solo use, the vector store alone is often enough. I'd probably make graph memory opt-in by default — it already is, actually, turned off unless you flip a flag."

> "The automation is still not fully seamless. The hook is smart enough to skip trivial prompts, but tuning what counts as 'durable' is an ongoing calibration. We use a signals mode that looks for specific language — and it works well — but it can miss things."

> "And the biggest open question: how do you let memories age gracefully? There's a decay system built in — memories get scored lower over time — and a garbage collector. But the right half-life for a 'durable fact' in a fast-moving codebase is genuinely hard. We also had to build a three-level auth fallback because corporate gateways kept breaking OAuth. Real-world messiness."

---

## Slide 12 — What's Next
**Visual:** A tower being built on top of the palace. New floors going up.

**Say:**
> "A few things on the roadmap. Multi-agent support is mostly there — you can share read-only memory across projects, which is useful when you're working on something that references a shared library or a design system. We want to harden that."

> "Consolidation — there's already a job that runs a proposer/adversary/judge loop to merge redundant memories, prune stale ones. A proposer suggests what to merge or prune. An adversary pushes back on information loss. A judge decides. It sounds like overkill until you watch it catch a bad merge. Making that more automated is on the list."

> "And I want to keep improving the inspection surface — a clean way to see what the system knows about you at any given moment, what changed last session, what it's forgotten."

---

## Slide 13 — The Takeaway
**Visual:** Back to the exterior of the palace — but now the gate is open. Warm light coming from inside.

**Say:**
> "Here's the thing: agents are not going to get persistent memory natively anytime soon. The providers are working on it, but it's a hard problem and the solutions will be opinionated in ways that may not fit your workflow."

> "Building your own is not as hard as it sounds. The whole stack is open source. It runs in Docker. It costs almost nothing. And the payoff — having an AI collaborator who actually remembers — is genuinely different."

> "The gate's open. You're welcome to walk in."

---

## Slide 14 — Close / Links
**Visual:** Minimal. Palace silhouette. GitHub link. QR code optional.

**Say:**
> "That's Mind Palace. Happy to take questions. The repo is public — link on screen. If you want to set it up and try it yourself, the README will walk you through it start to finish in about 20 minutes."

---

## Timing Guide

| Section | Slides | Target Time |
|---|---|---|
| Hook + Problem | 1–2 | ~2 min |
| What I Needed + What Existed | 3–4 | ~2.5 min |
| The Decision + Building the Stack | 5–6 | ~3.5 min |
| Memory Types + Manual Problem | 7–8 | ~2.5 min |
| Hook System | 9 | ~2 min |
| Real Impact | 10 | ~2 min |
| What I'd Change + What's Next | 11–12 | ~2 min |
| Takeaway + Close | 13–14 | ~1.5 min |
| **Total** | | **~18 min** |

---

## Screenshot Suggestions

- **Slide 8:** Terminal showing hook output injecting `additionalContext` into a Claude session
- **Slide 8:** The `mind_palace_hook_status.py` output — shows hook wired up, queue counts
- **Slide 9:** A real memory retrieval from your OTO project — something specific and personal
- **Slide 10:** The `memory_report.py` HTML report — the inspection surface in action
