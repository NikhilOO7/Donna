# 🧠 AUO Agentic Architecture: The Complete Lifecycle

This document details the multi-agent architecture powering the AUO meeting assistant across all three phases of the meeting lifecycle.

---

# 1. BEFORE Meeting: Research & Prep
*Goal: Tier-validated competitive intelligence.*

## 🏗️ **Multi-Agent System Overview**

Your BEFORE Meeting system implements a **sophisticated 7-step multi-agent workflow** where specialized AI agents collaborate to generate tier-validated competitive intelligence. Here's the complete architecture:

```
┌─────────────────────────────────────────────────────────────────┐
│                    AUO BEFORE MEETING                          │
│                 MULTI-AGENT ARCHITECTURE                       │
└─────────────────────────────────────────────────────────────────┘

INPUT: Meeting Details
   │
   ▼
┌─────────────────────────────────────────────────────────────────┐
│  STEP 1: COORDINATOR AGENT (Claude Haiku)                      │
│  Role: Topic Extraction & Research Planning                    │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │ • Analyze meeting context                               │   │
│  │ • Extract 3-5 specific research topics                 │   │
│  │ • Ensure topics are externally searchable              │   │
│  │ • Focus on competitive/market intelligence             │   │
│  └─────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
   │
   ▼
┌─────────────────────────────────────────────────────────────────┐
│  STEP 2-6: RESEARCH AGENTS (Parallel Processing)               │
│  Role: Tier-Validated Intelligence Gathering                   │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │ FOR EACH TOPIC (parallel execution):                   │   │
│  │                                                         │   │
│  │ Agent 2: EXA SEARCH AGENT                              │   │
│  │ • Semantic search across web                           │   │
│  │ • Find 10 initial sources per topic                    │   │
│  │ • Extract content and metadata                         │   │
│  │                                                         │   │
│  │ Agent 3: TIER VALIDATION AGENT                         │   │
│  │ • Apply domain tier classification                     │   │
│  │ • Tier 1: Bloomberg, Reuters, WSJ, SEC, Nike.com       │   │
│  │ • Tier 2: Forbes, TechCrunch, McKinsey, Footwear News  │   │
│  │ • REJECT: Tier 3+ sources (blogs, unknown domains)     │   │
│  │                                                         │   │
│  │ Agent 4: QUALITY SCORING AGENT                         │   │
│  │ • Assign credibility scores (Tier 1: 0.95, Tier 2: 0.85) │ │
│  │ • Rank sources by relevance and authority              │   │
│  │ • Select top 5 sources per topic                       │   │
│  │                                                         │   │
│  │ Agent 5: CONTENT EXTRACTION AGENT                      │   │
│  │ • Extract key excerpts and insights                    │   │
│  │ • Preserve source attribution                          │   │
│  │ • Calculate confidence scores                          │   │
│  └─────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
   │
   ▼
┌─────────────────────────────────────────────────────────────────┐
│  STEP 7: SYNTHESIS AGENT (Claude Sonnet 4.5)                  │
│  Role: Strategic Intelligence Synthesis                        │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │ • Analyze all tier-validated research                  │   │
│  │ • Generate executive summary                           │   │
│  │ • Extract key strategic insights                       │   │
│  │ • Identify competitive implications                    │   │
│  │ • Flag data gaps and recommendations                   │   │
│  │ • Maintain source transparency                         │   │
│  └─────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
   │
   ▼
OUTPUT: Tier-Validated Research Brief
```

---

# 2. DURING Meeting: Real-Time Intelligence
*Goal: Live memory, fact-checking, and strategic nudges.*

## 🏗️ **Real-Time Agentic Overview**

The DURING Meeting system uses a **low-latency streaming architecture** where a Listener Agent orchestrates tool usage to provide live insights.

```
┌─────────────────────────────────────────────────────────────────┐
│                    AUO DURING MEETING                          │
│                 REAL-TIME AGENTIC SYSTEM                       │
└─────────────────────────────────────────────────────────────────┘

INPUT: Live Audio Stream (WebSocket)
   │
   ▼
┌─────────────────────────────────────────────────────────────────┐
│  LISTENER AGENT (GPT-4o Realtime)                              │
│  Role: Orchestrator & Intent Detector                          │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │ • Transcribe speech with speaker ID                     │   │
│  │ • Detect strategic moments (triggers)                   │   │
│  │ • "Should I research this?" decision logic              │   │
│  │ • Maintain conversation context window                  │   │
│  └─────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
   │
   ▼
┌─────────────────────────────────────────────────────────────────┐
│  TOOL AGENTS (Function Calling)                                │
│  Role: Specialized Data Retrieval                              │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │                                                         │   │
│  │ Tool A: SOCIAL INTEL AGENT                              │   │
│  │ • Query: Instagram, Reddit, YouTube, Trends             │   │
│  │ • Goal: "What is the sentiment on this topic?"          │   │
│  │                                                         │   │
│  │ Tool B: CONTEXT AGENT (RAG)                             │   │
│  │ • Query: Internal Company Knowledge Base                │   │
│  │ • Goal: "What did we decide about this last time?"      │   │
│  │                                                         │   │
│  │ Tool C: SCRIBE AGENT                                    │   │
│  │ • Action: Log Decision / Action Item                    │   │
│  │ • Goal: "Capture this agreement formally."              │   │
│  └─────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
   │
   ▼
OUTPUT: UI Nudge Cards (JSON)
```

## 🔍 **Agent Specialization Breakdown**

### **Agent 1: Listener Agent (GPT-4o Realtime)**
```typescript
Role: "Live Session Orchestrator"
Model: gpt-4o-realtime-preview-2024-12-17
Specialization: Ultra-low latency speech-to-text & reasoning

System Instructions:
- "Transcribe speech accurately with speaker identification"
- "Detect strategic discussion moments"
- "Listen for questions about competitors, market trends"
- "Suggest: 'Should I research this topic?'"

Configuration:
- Voice: "alloy"
- Temperature: 0.3 (Focused)
```

### **Agent 2: Social Intel Agent**
```typescript
Role: "External Pulse Checker"
Function: `social-api-intelligence`

Capabilities:
- Instagram: Hashtag engagement & visual trends
- Reddit: Community sentiment & discussion threads
- YouTube: Video reviews & influencer opinions
- Google Trends: Search volume velocity

Output: Sentiment Score (-100 to +100) & Key Themes
```

---

# 3. POST Meeting: Synthesis & Action
*Goal: Automated administrative follow-up and strategic summary.*

## 🏗️ **Synthesis Architecture Overview**

The POST Meeting system employs a **Context-Aware Synthesis Pipeline** to transform raw transcripts and scattered insights into a coherent executive report.

```
┌─────────────────────────────────────────────────────────────────┐
│                     AUO POST MEETING                           │
│                  SYNTHESIS PIPELINE                            │
└─────────────────────────────────────────────────────────────────┘

INPUT: Meeting ID
   │
   ▼
┌─────────────────────────────────────────────────────────────────┐
│  STEP 1: DATA AGGREGATOR                                       │
│  Role: Context Assembly                                        │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │ • Fetch full transcript (Utterances)                    │   │
│  │ • Retrieve all generated Nudges (Insights)              │   │
│  │ • Collect logged Decisions & Action Items               │   │
│  │ • Load Meeting Metadata (Attendees, Duration)           │   │
│  └─────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
   │
   ▼
┌─────────────────────────────────────────────────────────────────┐
│  STEP 2: ANALYST AGENT (Claude Sonnet 4.5)                     │
│  Role: Strategic Summarization                                 │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │ • "Generate a comprehensive meeting summary"            │   │
│  │ • Synthesize conversation highlights                    │   │
│  │ • Integrate AI insights into the narrative              │   │
│  │ • Format decisions with owners and deadlines            │   │
│  │ • Identify follow-up opportunities                      │   │
│  └─────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
   │
   ▼
┌─────────────────────────────────────────────────────────────────┐
│  STEP 3: DELIVERY AGENT                                        │
│  Role: Formatting & Distribution                               │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │ • Format as Markdown or JSON                            │   │
│  │ • Generate HTML Email Template                          │   │
│  │ • Send via Postmark                                     │   │
│  │ • Archive to 'email_results' table                      │   │
│  └─────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
   │
   ▼
OUTPUT: Executive Summary Email
```

## 🔍 **Agent Specialization Breakdown**

### **Agent 1: Analyst Agent (Claude Sonnet 4.5)**
```typescript
Role: "Executive Secretary"
Model: claude-sonnet-4-5-20250929
Specialization: Long-context reasoning & structured writing

Prompt Engineering:
- "Create a structured meeting summary"
- "Executive Summary: 2-3 sentences capturing main outcomes"
- "Strategic Insights: AI insights that were valuable"
- "Decisions: Clear next steps with owners"
- Tone: Professional, concise, actionable

Input Context:
- Transcript (First 100 utterances + highlights)
- Nudges (Visual cards shown during meeting)
- Decisions (Formally tracked items)
```

### **Agent 2: Delivery Agent**
```typescript
Role: "Communications Officer"
Function: `send-results`

Logic:
- Verify recipient permissions
- Check for duplicate sends
- Render responsive HTML email
- Track delivery status (Postmark Message ID)
```

---

## 🚀 **Why This Architecture is Superior**

1.  **Phase-Specific Optimization**:
    *   **Pre-Meeting**: Optimized for *depth* (Exa + Tier Validation).
    *   **During-Meeting**: Optimized for *speed* (Realtime API + Function Calling).
    *   **Post-Meeting**: Optimized for *coherence* (Claude Sonnet + Context Aggregation).

2.  **Model Diversity**:
    *   Uses **Claude Haiku** for fast logic (Topic Extraction).
    *   Uses **GPT-4o Realtime** for low-latency voice (Live Interaction).
    *   Uses **Claude Sonnet 4.5** for high-quality writing (Final Synthesis).

3.  **Data Continuity**:
    *   Insights generated in *Pre-Meeting* are available in *During-Meeting*.
    *   Nudges shown in *During-Meeting* are cited in *Post-Meeting* summaries.
    *   Decisions tracked in *During-Meeting* become *Post-Meeting* action items.
