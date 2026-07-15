# PROJECT_CONTEXT.md

# Semantic Knowledge Compiler (SKC)

## Project Context (Source of Truth)

Version: 1.0

------------------------------------------------------------------------

# Purpose of this Document

This document captures the architectural decisions and vision
established so far. It is intended to be shared with future AI
assistants or engineers so they can continue development without
redesigning the platform.

Unless explicitly instructed otherwise, this document should be treated
as the project's source of truth.

------------------------------------------------------------------------

# Project Vision

The project is an **Enterprise Semantic Knowledge Compiler (SKC)**.

It is **not**:

-   a chatbot
-   a Text-to-SQL engine
-   a GraphRAG system
-   a reporting platform

Its only responsibility is to transform enterprise metadata into a
governed Semantic Knowledge Graph.

The graph is later consumed by other systems.

------------------------------------------------------------------------

# Problem Statement

Enterprise databases contain rich structural information but very little
explicit business meaning.

Business knowledge is scattered across:

-   DDL
-   sample data
-   SQL queries
-   BI reports
-   business glossaries
-   SME knowledge

Current LLM-only ontology generation approaches are unreliable because
they attempt to infer complete business knowledge from incomplete
inputs.

SKC aims to solve this by combining deterministic metadata extraction,
targeted semantic inference, confidence scoring, and human governance.

------------------------------------------------------------------------

# Core Philosophy

Database → Stores business data.

Semantic Graph → Stores business knowledge.

Application Code → Implements compiler behavior.

Business knowledge must never be hardcoded into application code.

------------------------------------------------------------------------

# Product Goal

Compile enterprise metadata into a reusable Semantic Knowledge Graph
that contains:

-   Business Entities
-   Business Concepts
-   Ontology
-   Metrics
-   Business Rules
-   Join Intelligence
-   Grain Intelligence
-   Security Metadata
-   Time Intelligence
-   Provenance
-   Learning Metadata

------------------------------------------------------------------------

# High-Level Architecture

Enterprise Metadata │ ▼ Semantic Knowledge Compiler │ ▼ Semantic
Knowledge Graph (Neo4j)

The compiler is an offline platform.

It does not answer user questions.

------------------------------------------------------------------------

# Compiler Philosophy

Treat the platform like a traditional compiler.

Enterprise Metadata ↓ Metadata Parser ↓ Metadata Intermediate
Representation (MIR) ↓ Deterministic Enrichment ↓ Semantic Enrichment ↓
Knowledge Intermediate Representation (KIR) ↓ Validation ↓ Human Review
↓ Graph Generator ↓ Neo4j Semantic Knowledge Graph

------------------------------------------------------------------------

# Intermediate Representations

## Metadata IR (MIR)

Contains only technical metadata.

Examples:

-   Database
-   Schema
-   Table
-   Column
-   Primary Key
-   Foreign Key
-   Constraint
-   Index

No business knowledge.

## Knowledge IR (KIR)

Contains semantic knowledge.

Examples:

-   Business Entity
-   Metric
-   Rule
-   Synonym
-   Business Relationship
-   Grain
-   Security
-   Time Intelligence

KIR is the final representation before graph generation.

------------------------------------------------------------------------

# Compiler Pipeline

1.  Metadata Connectors
2.  Schema Parser
3.  Schema Graph Builder
4.  Data Profiler
5.  Semantic Inferencer
6.  Relationship Analyzer
7.  Metric Discovery
8.  Business Rule Discovery
9.  Confidence Engine
10. Validation Engine
11. Human Review
12. Graph Generator

Every stage has one responsibility.

------------------------------------------------------------------------

# LLM Philosophy

LLMs are used only for narrowly scoped semantic reasoning.

Examples:

-   Identify a business entity.
-   Suggest synonyms.
-   Describe a table.
-   Infer likely business concept.

LLMs must never:

-   build the complete ontology
-   write directly to Neo4j
-   bypass review
-   invent unsupported business rules

------------------------------------------------------------------------

# Human-in-the-Loop

All inferred knowledge becomes Candidate Knowledge.

Each candidate contains:

-   confidence
-   provenance
-   evidence
-   source
-   review status
-   version

Low-confidence knowledge must be reviewed before publication.

------------------------------------------------------------------------

# Plugin Philosophy

The compiler core is industry-agnostic.

Industry-specific knowledge is delivered through plugins.

Example plugins:

-   Insurance
-   Banking
-   Healthcare
-   Retail

Plugins contribute:

-   ontology
-   metrics
-   rules
-   synonyms
-   validation

The compiler core never contains domain-specific logic.

------------------------------------------------------------------------

# Engineering Principles

1.  Business knowledge belongs in Neo4j.
2.  Compiler behavior belongs in code.
3.  Deterministic extraction before AI inference.
4.  Every stage communicates through defined IRs.
5.  Every inference is traceable.
6.  Every inference has confidence.
7.  Every inference is reviewable.
8.  Every build is versioned.
9.  Components remain independently testable.
10. Plugin architecture is mandatory.

------------------------------------------------------------------------

# Major Architectural Decisions

-   Use a compiler architecture instead of direct graph generation.
-   Use two intermediate representations (MIR and KIR).
-   Separate deterministic and semantic processing.
-   Introduce a Confidence Engine before publication.
-   Require human review for uncertain knowledge.
-   Publish only approved knowledge to Neo4j.
-   Support incremental recompilation.
-   Preserve provenance for every node and relationship.

------------------------------------------------------------------------

# Proposed Repository

docs/ src/ plugins/ tests/ examples/ configs/ scripts/

Compiler stages are isolated modules.

------------------------------------------------------------------------

# Long-Term Roadmap

Phase 1 Architecture & Specifications

Phase 2 Compiler Foundation

Phase 3 Metadata Processing

Phase 4 Semantic Enrichment

Phase 5 Graph Generation

Phase 6 Governance & Review

Phase 7 Production Hardening

------------------------------------------------------------------------

# Future Discussions

Future conversations should assume this architecture unless explicitly
changed.

New ideas should extend the architecture rather than redesign it.

When proposing changes:

-   explain motivation
-   explain trade-offs
-   explain impact
-   preserve backward compatibility whenever possible.

End of Context.
