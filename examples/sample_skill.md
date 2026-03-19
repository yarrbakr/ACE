---
name: python_code_generation
version: "1.0.0"
description: "Generate Python code from natural language descriptions"
parameters:
  prompt: {type: string, description: "What code to generate"}
  language: {type: string, default: "python"}
returns:
  code: {type: string, description: "Generated source code"}
  language: {type: string}
pricing:
  currency: AGC
  model: per_call
  amount: 50
tags: [python, code-generation, programming]
---

# Python Code Generation

This skill generates Python code from natural language prompts.

## Examples

- "Write a function to sort a list" → returns working sort function
- "Create a FastAPI endpoint for user login" → returns endpoint code
