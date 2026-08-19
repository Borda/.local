"""MkDocs hook: inject JSON-LD schema markup into homepage <head>."""

_SCHEMA_JSON_LD = """\
<script type="application/ld+json">
  {
    "@context": "https://schema.org",
    "@graph": [
      {
        "@type": "Organization",
        "name": "AI-Rig by Borda",
        "url": "https://borda.github.io/AI-Rig/",
        "description": "Six Claude Code plugins and Codex Rig for Python/ML OSS development.",
        "sameAs": ["https://github.com/Borda/AI-Rig"]
      },
      {
        "@type": "WebSite",
        "name": "Borda's AI-Rig",
        "url": "https://borda.github.io/AI-Rig/",
        "description": "Claude Code and OpenAI Codex plugin suite for Python/ML OSS development",
        "potentialAction": {
          "@type": "SearchAction",
          "target": {
            "@type": "EntryPoint",
            "urlTemplate": "https://borda.github.io/AI-Rig/search/?q={search_term_string}"
          },
          "query-input": "required name=search_term_string"
        }
      },
      {
        "@type": "SoftwareApplication",
        "name": "Borda's AI-Rig",
        "applicationCategory": "DeveloperApplication",
        "operatingSystem": "macOS, Linux, Windows",
        "description": "Six Claude Code plugins plus Codex Rig for Python/ML OSS development. Specialist roles, calibrated workflows, and validate-first discipline.",
        "url": "https://borda.github.io/AI-Rig/",
        "downloadUrl": "https://github.com/Borda/AI-Rig",
        "offers": {
          "@type": "Offer",
          "price": "0",
          "priceCurrency": "USD"
        },
        "author": {
          "@type": "Person",
          "name": "Jiri Borovec",
          "url": "https://github.com/Borda"
        },
        "featureList": [
          "16 specialist Claude Code agents across independently installable plugins",
          "Validate-first Python development with explicit reproduction and acceptance gates",
          "Evidence-backed issue, pull request, feedback-resolution, and release-readiness workflows",
          "Reviewable ML research planning, execution, verification, ablation, and retrospective workflows",
          "Static Python indexing, structural queries, test-impact analysis, and reference renames",
          "13 Codex workflows, one lifecycle manager, 15 role cards, and shared artifact gates",
          "Bidirectional Claude Code and Codex bridge for bounded implement, advise, and review calls"
        ],
        "hasPart": [
          {
            "@type": "SoftwareApplication",
            "name": "foundry",
            "description": "Claude configuration and workflow maintenance: 11 skills, 10 specialist agents, rules, hooks, audit, calibration, and reviewed instruction distillation.",
            "url": "https://borda.github.io/AI-Rig/cc_foundry/"
          },
          {
            "@type": "SoftwareApplication",
            "name": "oss",
            "description": "Five OSS maintainer skills for analysis, PR review, feedback resolution, release-readiness assessment, and setup.",
            "url": "https://borda.github.io/AI-Rig/cc_oss/"
          },
          {
            "@type": "SoftwareApplication",
            "name": "develop",
            "description": "Seven validate-first Python skills for planning, features, fixes, refactors, debugging, review, and setup.",
            "url": "https://borda.github.io/AI-Rig/cc_develop/"
          },
          {
            "@type": "SoftwareApplication",
            "name": "research",
            "description": "Ten reviewable ML research skills for literature, planning, methodology review, bounded execution, verification, ablation, retrospectives, Kaggle, and setup.",
            "url": "https://borda.github.io/AI-Rig/cc_research/"
          },
          {
            "@type": "SoftwareApplication",
            "name": "codemap-py",
            "description": "Six dual-runtime skills for static Python indexing, structural queries, test impact, reference renames, integration, and telemetry debriefs.",
            "url": "https://borda.github.io/AI-Rig/codemap-py/"
          },
          {
            "@type": "SoftwareApplication",
            "name": "Codex Rig",
            "description": "Thirteen evidence-first Codex workflows, one legacy-shim lifecycle manager, fifteen role cards, shared gates, and reviewable artifacts.",
            "url": "https://borda.github.io/AI-Rig/codex-rig/"
          },
          {
            "@type": "SoftwareApplication",
            "name": "bridge",
            "description": "Bidirectional Claude Code and Codex bridge: bounded implement, advise, and review calls with explicit models, budgets, compact envelopes, and recursion safety.",
            "url": "https://borda.github.io/AI-Rig/bridge_cc-codex/"
          }
        ]
      }
    ]
  }
</script>"""


def on_post_page(output, page, config):
    """Inject JSON-LD schema markup into homepage <head>."""
    if page.url in ("", ".", "./"):
        return output.replace("</head>", _SCHEMA_JSON_LD + "\n</head>", 1)
    return output
