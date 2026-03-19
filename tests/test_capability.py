"""Tests for the capability module — parser, agent card, registry."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from ace.core.capability import (
    CapabilityRegistry,
    SkillDefinition,
    SkillParser,
    SkillPricing,
    generate_agent_card,
)
from ace.core.exceptions import SkillParseError


# ── Fixtures ─────────────────────────────────────────────────

VALID_SKILL_MD = """\
---
name: python_code_generation
version: "1.0.0"
description: "Generate Python code from natural language descriptions"
parameters:
  prompt: {type: string, description: "What code to generate"}
returns:
  code: {type: string, description: "Generated source code"}
pricing:
  currency: AGC
  model: per_call
  amount: 50
tags: [python, code-generation, programming]
---

# Python Code Generation

This skill generates Python code from natural language prompts.
"""


SIMPLE_PRICE_SKILL_MD = """\
---
name: text_summarizer
version: "2.0.0"
description: "Summarize long text into bullet points"
price: 25
tags: [nlp, summarization]
---

# Text Summarizer
"""


@pytest.fixture()
def valid_skill() -> SkillDefinition:
    return SkillParser.parse(VALID_SKILL_MD)


# ── SkillPricing tests ──────────────────────────────────────


class TestSkillPricing:
    def test_valid_pricing(self) -> None:
        pricing = SkillPricing(currency="AGC", model="per_call", amount=50)
        assert pricing.amount == 50
        assert pricing.model == "per_call"

    def test_negative_amount_rejected(self) -> None:
        with pytest.raises(ValueError, match="greater than 0"):
            SkillPricing(amount=-1)

    def test_zero_amount_rejected(self) -> None:
        with pytest.raises(ValueError, match="greater than 0"):
            SkillPricing(amount=0)

    def test_invalid_model_rejected(self) -> None:
        with pytest.raises(ValueError):
            SkillPricing(amount=10, model="invalid")  # type: ignore[arg-type]


# ── SkillParser tests ────────────────────────────────────────


class TestSkillParser:
    def test_parse_valid_skill(self, valid_skill: SkillDefinition) -> None:
        assert valid_skill.name == "python_code_generation"
        assert valid_skill.version == "1.0.0"
        assert valid_skill.pricing.amount == 50
        assert valid_skill.pricing.model == "per_call"
        assert "python" in valid_skill.tags
        assert valid_skill.parameters == {
            "prompt": {"type": "string", "description": "What code to generate"}
        }

    def test_parse_simple_price_shorthand(self) -> None:
        skill = SkillParser.parse(SIMPLE_PRICE_SKILL_MD)
        assert skill.name == "text_summarizer"
        assert skill.pricing.amount == 25
        assert skill.pricing.model == "per_call"
        assert skill.pricing.currency == "AGC"

    def test_missing_frontmatter_raises(self) -> None:
        with pytest.raises(SkillParseError, match="missing YAML frontmatter"):
            SkillParser.parse("No frontmatter here, just text")

    def test_empty_frontmatter_raises(self) -> None:
        with pytest.raises(SkillParseError, match="empty"):
            SkillParser.parse("---\n---\nBody only")

    def test_missing_name_raises(self) -> None:
        content = """\
---
version: "1.0.0"
description: "Test"
pricing:
  amount: 10
---
"""
        with pytest.raises(SkillParseError, match="Validation failed"):
            SkillParser.parse(content)

    def test_missing_pricing_raises(self) -> None:
        content = """\
---
name: test_skill
version: "1.0.0"
description: "Test skill"
---
"""
        with pytest.raises(SkillParseError, match="Validation failed"):
            SkillParser.parse(content)

    def test_invalid_pricing_model_raises(self) -> None:
        content = """\
---
name: test_skill
version: "1.0.0"
description: "Test"
pricing:
  model: bogus
  amount: 10
---
"""
        with pytest.raises(SkillParseError, match="Validation failed"):
            SkillParser.parse(content)

    def test_negative_price_raises(self) -> None:
        content = """\
---
name: test_skill
version: "1.0.0"
description: "Test"
pricing:
  amount: -5
---
"""
        with pytest.raises(SkillParseError, match="Validation failed"):
            SkillParser.parse(content)

    def test_invalid_version_raises(self) -> None:
        content = """\
---
name: test_skill
version: "abc"
description: "Test"
pricing:
  amount: 10
---
"""
        with pytest.raises(SkillParseError, match="Validation failed"):
            SkillParser.parse(content)

    def test_extra_fields_succeed(self) -> None:
        content = """\
---
name: test_skill
version: "1.0.0"
description: "Test"
pricing:
  amount: 10
custom_field: "extra data"
---
"""
        skill = SkillParser.parse(content)
        assert skill.name == "test_skill"

    def test_markdown_body_stored(self, valid_skill: SkillDefinition) -> None:
        assert "Python Code Generation" in valid_skill.body
        assert "natural language prompts" in valid_skill.body

    def test_tags_normalized_to_lowercase(self) -> None:
        content = """\
---
name: test_skill
version: "1.0.0"
description: "Test"
pricing:
  amount: 10
tags: [UPPER, MiXeD]
---
"""
        skill = SkillParser.parse(content)
        assert skill.tags == ["upper", "mixed"]

    def test_sample_skill_file_parses(self) -> None:
        """Verify that examples/sample_skill.md is always valid."""
        sample_path = Path(__file__).parent.parent / "examples" / "sample_skill.md"
        if not sample_path.exists():
            pytest.skip("sample_skill.md not found")
        content = sample_path.read_text(encoding="utf-8")
        skill = SkillParser.parse(content)
        assert skill.name == "python_code_generation"
        assert skill.pricing.amount == 50


# ── Agent Card tests ─────────────────────────────────────────


class TestAgentCard:
    def test_includes_all_capabilities(self, valid_skill: SkillDefinition) -> None:
        card = generate_agent_card(
            name="TestAgent",
            description="Test",
            url="http://localhost:8080",
            skills=[valid_skill],
            aid="aid:test123",
            public_key_b64="AAAA",
        )
        assert len(card["capabilities"]) == 1
        assert card["capabilities"][0]["id"] == "python_code_generation"
        assert card["capabilities"][0]["pricing"]["amount"] == 50

    def test_includes_auth_with_public_key(self, valid_skill: SkillDefinition) -> None:
        card = generate_agent_card(
            name="TestAgent",
            description="Test",
            url="http://localhost:8080",
            skills=[valid_skill],
            aid="aid:test123",
            public_key_b64="PUBKEY_BASE64",
        )
        assert card["authentication"]["type"] == "ed25519"
        assert card["authentication"]["public_key"] == "PUBKEY_BASE64"

    def test_includes_correct_url(self, valid_skill: SkillDefinition) -> None:
        card = generate_agent_card(
            name="TestAgent",
            description="Test",
            url="http://myhost:9090",
            skills=[valid_skill],
            aid="aid:test123",
            public_key_b64="X",
        )
        assert card["url"] == "http://myhost:9090"
        assert card["aid"] == "aid:test123"

    def test_zero_skills_empty_capabilities(self) -> None:
        card = generate_agent_card(
            name="EmptyAgent",
            description="No skills",
            url="http://localhost:8080",
            skills=[],
            aid="aid:empty",
            public_key_b64="X",
        )
        assert card["capabilities"] == []


# ── CapabilityRegistry tests ─────────────────────────────────


def _make_card(name: str, price: int, tags: str = "", desc: str = "") -> dict[str, Any]:
    """Helper to build a minimal agent card for testing."""
    return {
        "name": f"Agent-{name}",
        "capabilities": [
            {
                "name": name,
                "description": desc or f"Skill {name}",
                "pricing": {"currency": "AGC", "model": "per_call", "amount": price},
                "tags": tags.split(",") if tags else [],
            }
        ],
        "aid": f"aid:{name}",
    }


class TestCapabilityRegistry:
    @pytest.fixture()
    async def registry(self, tmp_db_path: Path) -> CapabilityRegistry:
        reg = CapabilityRegistry(tmp_db_path)
        await reg.initialize()
        return reg

    async def test_register_then_get(self, registry: CapabilityRegistry) -> None:
        card = _make_card("alpha", 100)
        await registry.register("aid:alpha", card)
        result = await registry.get_agent_card("aid:alpha")
        assert result is not None
        assert result["name"] == "Agent-alpha"

    async def test_unregister_removes_card(self, registry: CapabilityRegistry) -> None:
        card = _make_card("beta", 50)
        await registry.register("aid:beta", card)
        await registry.unregister("aid:beta")
        assert await registry.get_agent_card("aid:beta") is None

    async def test_unknown_aid_returns_none(self, registry: CapabilityRegistry) -> None:
        assert await registry.get_agent_card("aid:nonexistent") is None

    async def test_search_by_name(self, registry: CapabilityRegistry) -> None:
        await registry.register("aid:a1", _make_card("python_coder", 50))
        results = await registry.search("python")
        assert len(results) == 1
        assert results[0]["name"] == "python_coder"

    async def test_search_by_description(self, registry: CapabilityRegistry) -> None:
        card = _make_card("translator", 30, desc="Translate natural language text")
        await registry.register("aid:t1", card)
        results = await registry.search("natural language")
        assert len(results) == 1

    async def test_search_by_tag(self, registry: CapabilityRegistry) -> None:
        card = _make_card("nlp_tool", 20, tags="nlp,text-processing")
        await registry.register("aid:n1", card)
        results = await registry.search("nlp")
        assert len(results) == 1

    async def test_search_max_price_filter(self, registry: CapabilityRegistry) -> None:
        await registry.register("aid:cheap", _make_card("cheap_skill", 10))
        await registry.register("aid:expensive", _make_card("expensive_skill", 500))
        results = await registry.search("skill", max_price=100)
        assert len(results) == 1
        assert results[0]["name"] == "cheap_skill"

    async def test_search_no_matches(self, registry: CapabilityRegistry) -> None:
        await registry.register("aid:x", _make_card("something", 10))
        results = await registry.search("zzz_nonexistent_xyz")
        assert results == []

    async def test_search_multi_word_or(self, registry: CapabilityRegistry) -> None:
        await registry.register("aid:a", _make_card("python_gen", 10))
        await registry.register("aid:b", _make_card("rust_compiler", 20))
        results = await registry.search("python rust")
        assert len(results) == 2

    async def test_register_overwrites(self, registry: CapabilityRegistry) -> None:
        card1 = _make_card("mover", 10)
        card2 = _make_card("mover", 99)
        await registry.register("aid:same", card1)
        await registry.register("aid:same", card2)
        results = await registry.search("mover")
        assert len(results) == 1
        assert results[0]["price"] == 99

    async def test_list_skills(self, registry: CapabilityRegistry) -> None:
        await registry.register("aid:ls1", _make_card("skill_a", 10))
        await registry.register("aid:ls2", _make_card("skill_b", 20))
        skills = await registry.list_skills()
        assert len(skills) == 2
        names = {s["name"] for s in skills}
        assert names == {"skill_a", "skill_b"}
