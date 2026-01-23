# Blockers Log

> Track blocked items, workaround attempts, and resolutions.

---

## Active Blockers

<!--
## [BLOCKER-001] Brief Description
**Blocking Task**: TASK-XXX
**Since**: [Date]
**Severity**: CRITICAL | HIGH | MEDIUM | LOW

### Problem
Detailed description of what's blocked and why.

### Attempted Solutions
1. [What was tried] → [Result]
2. [What was tried] → [Result]

### Potential Solutions
- [ ] [Idea to try]
- [ ] [Idea to try]

### Workaround
[Temporary solution if any]

### Needs
[What would unblock this - user input, external change, etc.]
-->

---

## Resolved Blockers

<!--
Move here when resolved with:
- Resolution date
- How it was fixed
- Lessons learned
-->

---

## Blocker Patterns

### BC Modal Dialog Blocking
**Pattern**: API calls trigger UI dialogs that can't be dismissed programmatically
**Common Solutions**:
- Background sessions with GuiAllowed = false
- ConfirmHandler/MessageHandler in AL tests
- Codeunit wrappers that suppress UI
- Queue-based async processing

### BC Permission Issues
**Pattern**: 403 Forbidden on custom API endpoints
**Common Solutions**:
- Review permission sets for custom objects
- Check entitlements for SaaS
- Verify indirect permissions
- Test with elevated permissions to isolate issue

### BC API Rate Limiting
**Pattern**: 429 errors during bulk operations
**Common Solutions**:
- Implement exponential backoff
- Batch operations
- Cache frequently accessed data
- Spread operations over time

### Authentication Token Issues
**Pattern**: 401 errors, token expiry
**Common Solutions**:
- Implement token refresh logic
- Check client secret expiry
- Verify scope is correct
- Ensure app has required permissions in Azure AD

---

## Escalation Criteria

### Escalate to User When:
- Blocked > 24 hours with no workaround
- Requires credentials or access not available
- Business decision needed
- External dependency (vendor, API provider)
- Security-related blocker

### Try Harder Before Escalating:
- Code-level problems (keep debugging)
- Documentation gaps (keep researching)
- Integration issues (try different approaches)
- Performance problems (optimize first)
