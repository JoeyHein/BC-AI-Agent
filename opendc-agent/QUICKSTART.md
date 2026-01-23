# OPENDC Agent System - Quick Start Guide

## Overview

This is an autonomous agent orchestration system designed for Claude Code. It enables Claude to work on OPENDC projects (Business Central integration, door configurator, back-office automation) with minimal human intervention.

## Installation

1. **Copy to your project root**:
   ```bash
   cp -r opendc-agent/* /path/to/your/opendc/project/
   ```

2. **Rename main file** (Claude Code looks for CLAUDE.md):
   ```bash
   # The CLAUDE.md file is already named correctly
   # Just ensure it's in your project root
   ```

3. **Set up environment variables**:
   ```bash
   cp config/env.template .env
   # Fill in your BC credentials and other config
   ```

## How It Works

### Autonomous Execution
- Claude reads CLAUDE.md at session start
- Works through tasks without asking permission for implementation details
- Batches 5-10 key decision questions before pausing

### Question Batching
Instead of asking every small question, Claude will:
1. Collect questions in `tasks/pending_questions.md`
2. Continue working on solvable tasks
3. Present questions when 5+ accumulate OR when blocked
4. Resume after you answer

### Specialized Agents
The orchestrator delegates to specialized agents for focused work:

| Agent | Purpose | File |
|-------|---------|------|
| Research | Documentation, API research | `agents/research.md` |
| Code | Writing, debugging, refactoring | `agents/code.md` |
| Integration | BC API, webhooks, sync | `agents/integration.md` |
| Test | Unit tests, integration tests | `agents/test.md` |
| Docs | README, API docs, ADRs | `agents/docs.md` |
| Deploy | Scripts, CI/CD, environments | `agents/deploy.md` |

## Usage

### Starting a Session
```
You: Start working on [objective]

Claude: [Reads CLAUDE.md, checks tasks, begins autonomous work]
```

### Giving Direction
```
You: Focus on BC API integration for sales orders

Claude: [Updates sprint, begins work, batches questions]
```

### Answering Questions
```
Claude: 
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🛑 DECISION CHECKPOINT
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Q1: Should we use OAuth 2.0 or Basic Auth?
Q2: Preferred error handling strategy?
...

You: Q1: A (OAuth), Q2: B, Q3: your call

Claude: [Resumes autonomous work with your decisions]
```

### Slash Commands
- `/status` - Current progress
- `/questions` - Force show pending questions
- `/blockers` - List blocked items
- `/sprint` - Current sprint tasks
- `/deploy` - Run deployment
- `/test` - Run test suite

## File Structure

```
your-project/
├── CLAUDE.md              # Main orchestrator (read this first)
├── agents/                # Specialized agent prompts
│   ├── research.md
│   ├── code.md
│   ├── integration.md
│   ├── test.md
│   ├── docs.md
│   └── deploy.md
├── config/                # Configuration files
│   ├── bc_api.md          # BC API reference
│   └── env.template       # Environment variables template
├── tasks/                 # Task management
│   ├── current_sprint.md  # Active work
│   ├── backlog.md         # Future work
│   ├── blockers.md        # Blocked items
│   ├── completed.md       # Done work
│   └── pending_questions.md  # Questions for user
├── scripts/               # Deployment & utility scripts
├── docs/                  # Generated documentation
└── templates/             # Code templates
```

## Customization

### Adding Project Context
Edit `CLAUDE.md` to add:
- Specific business rules
- Code conventions
- Integration details
- Team preferences

### Adding New Agents
Create new agent files in `agents/` following the existing format:
1. Define the role
2. List capabilities
3. Provide templates
4. Document integration points

### Modifying Autonomy Level
In `CLAUDE.md`, adjust:
- Question batch size (default: 5-10)
- What requires questions vs autonomous decisions
- Escalation criteria

## Best Practices

1. **Start sessions with clear objectives** - "Work on X" is better than vague requests
2. **Let Claude batch questions** - Resist urge to interrupt for small decisions
3. **Review completed.md** - See what was accomplished and learnings
4. **Check blockers.md** - Some blockers may need your input
5. **Trust the process** - Claude will ask when it truly needs input

## Troubleshooting

### Claude keeps asking questions
- Check if questions are truly key decisions
- Adjust CLAUDE.md criteria for what needs questions

### Not enough progress
- Check blockers.md for stuck items
- Review pending_questions.md for unanswered items

### Wrong direction
- Interrupt with clarification
- Claude will adjust and continue

## Support

This system is designed for OPENDC's specific needs:
- Business Central integration
- Door configurator development  
- Back-office automation
- Alberta, Canada business context

Adapt as your project scope grows!
