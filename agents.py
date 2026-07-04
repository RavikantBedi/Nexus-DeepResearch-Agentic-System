from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langchain_core.output_parsers.json import JsonOutputParser
from tools import web_search, scrape_url
from dotenv import load_dotenv
import os
from langchain_groq import ChatGroq

load_dotenv()

# ── Regular LLM ───────────────────────────────────────────────────────────────
llm = ChatGroq(
    model="llama-3.1-8b-instant",
    api_key=os.getenv("GROQ_API_KEY"),
    temperature=0.2,
    max_retries=5,
    timeout=120
)

# ── JSON-output LLM (for critic & diagram) ────────────────────────────────────
json_llm = ChatGroq(
    model="llama-3.1-8b-instant",
    api_key=os.getenv("GROQ_API_KEY"),
    temperature=0,
    max_retries=5,
    timeout=60
).bind(response_format={"type": "json_object"})


# ── Agent Builders (using simple chain approach for reliability) ───────────────
def build_search_agent():
    """Returns a simple callable that performs web search."""
    class SearchAgent:
        def invoke(self, params):
            query = params["messages"][0][1] if isinstance(params["messages"][0], tuple) else params["messages"][0]
            result = web_search.invoke(query)
            return {"messages": [("ai", result)]}
    return SearchAgent()

def build_reader_agent():
    """Returns a callable that scrapes URLs from search results."""
    class ReaderAgent:
        def invoke(self, params):
            msg = params["messages"][0][1] if isinstance(params["messages"][0], tuple) else params["messages"][0]
            # Extract first URL from message
            import re
            urls = re.findall(r'https?://[^\s\'"<>]+', msg)
            if urls:
                content = scrape_url.invoke(urls[0])
            else:
                content = "No URL found to scrape."
            return {"messages": [("ai", content)]}
    return ReaderAgent()


# ── Outline Chain ─────────────────────────────────────────────────────────────
outline_prompt = ChatPromptTemplate.from_messages([
    ("system", "You are a Senior Research Director at a leading academic institution. You create rigorous, comprehensive research paper outlines."),
    ("human", """Create a 4-5 section outline for a comprehensive academic research paper.

Topic: {topic}
Research Gathered: {research}

Output ONLY section titles, one per line, exactly in this format:
Section 1: Introduction & Background
Section 2: [Title]
Section 3: [Title]
...

The outline must flow logically: from context/background through methodology, in-depth analysis, key findings, future directions, and conclusion.
Do NOT include sub-bullets or any other text."""),
])
outline_chain = outline_prompt | llm | StrOutputParser()


# ── Section Writer Chain ──────────────────────────────────────────────────────
section_prompt = ChatPromptTemplate.from_messages([
    ("system", """You are an elite Senior Research Scientist at a top research university.
Write comprehensive, highly accurate, peer-review-quality academic content.
Use evidence-based analysis, cite data from the research provided, and maintain a formal academic tone throughout."""),
    ("human", """Write a comprehensive, in-depth academic section for a research paper.

Topic: {topic}
Full Paper Outline: {outline}
Current Section to Write: {section_title}

Research Data Available:
{research}

Instructions:
- Write 200-250 words of dense, analytical, factual content for THIS SECTION ONLY
- Use formal academic writing: topic sentences, evidence, analysis, transitions
- Ground every claim in the provided research data
- If this section covers systems, processes, or architecture, include ONE Mermaid.js diagram:
  ```mermaid
  graph LR
      A[Component] --> B[Component] --> C[Output]
  ```
- Format strictly in Markdown with proper headings, sub-headings, and lists where appropriate"""),
])
section_writer_chain = section_prompt | llm | StrOutputParser()


# ── Architecture Diagram Chain ────────────────────────────────────────────────
diagram_prompt = ChatPromptTemplate.from_messages([
    ("system", """You are a technical systems architect. You must output ONLY valid JSON and nothing else.
The JSON represents a system architecture or process flow diagram."""),
    ("human", """Analyze the topic and research, then generate a JSON diagram description.

Topic: {topic}
Research Summary: {research_summary}

You MUST output ONLY this JSON object (no markdown, no extra text):
{{
  "title": "Specific Architecture Title Here",
  "subtitle": "Brief one-line description of what this diagram shows",
  "nodes": [
    {{"id": "n1", "label": "Component Name", "type": "input"}},
    {{"id": "n2", "label": "Component Name", "type": "process"}},
    {{"id": "n3", "label": "Component Name", "type": "process"}},
    {{"id": "n4", "label": "Component Name", "type": "process"}},
    {{"id": "n5", "label": "Component Name", "type": "output"}}
  ],
  "edges": [
    {{"from": "n1", "to": "n2", "label": ""}},
    {{"from": "n2", "to": "n3", "label": ""}},
    {{"from": "n3", "to": "n4", "label": ""}},
    {{"from": "n4", "to": "n5", "label": ""}}
  ]
}}

Rules:
- 5-7 nodes total
- Node labels must be concise (2-4 words maximum), highly specific to the topic
- Node types: "input", "process", "decision", "output", "storage"
- Edges define the actual data/control flow
- Make it reflect the ACTUAL topic architecture, not generic steps"""),
])
diagram_chain = diagram_prompt | json_llm | JsonOutputParser()


# ── Critic Chain (JSON output) ────────────────────────────────────────────────
critic_prompt = ChatPromptTemplate.from_messages([
    ("system", """You are a rigorous peer reviewer for a top academic journal.
Evaluate research papers on depth, accuracy, structure, and academic rigor.
You MUST output ONLY valid JSON."""),
    ("human", """Evaluate this research report as a peer reviewer would.

Report:
{report}

Score criteria (each worth 2.5 points, total = 10):
1. Academic Depth & Analysis
2. Factual Accuracy & Evidence
3. Structure & Flow
4. Academic Tone & Writing Quality

Output ONLY this JSON (no other text):
{{
  "score": 8.5,
  "strengths": [
    "Specific strength 1",
    "Specific strength 2",
    "Specific strength 3"
  ],
  "improvements": [
    "Specific improvement needed 1",
    "Specific improvement needed 2",
    "Specific improvement needed 3"
  ],
  "verdict": "One compelling sentence summarizing the overall quality"
}}"""),
])
critic_chain = critic_prompt | json_llm | JsonOutputParser()


# ── Refiner Chain ─────────────────────────────────────────────────────────────
refiner_prompt = ChatPromptTemplate.from_messages([
    ("system", """You are an elite Senior Research Scientist performing a major revision of your research paper.
You take peer reviewer feedback seriously and make substantial, targeted improvements."""),
    ("human", """Substantially revise this research paper based on the peer reviewer's specific feedback.

Topic: {topic}

Reviewer's Requested Improvements:
{feedback}

Current Paper Draft:
{report}

Revision Requirements:
- Address EVERY improvement point specifically
- Expand analytical depth in sections identified as weak
- Add more specific evidence, data, and examples from the research
- Improve transitions and academic flow
- Retain and enhance all Mermaid.js diagrams
- The revised paper should be noticeably better and longer than the original

Output the complete, fully revised paper in Markdown format."""),
])
refiner_chain = refiner_prompt | llm | StrOutputParser()
