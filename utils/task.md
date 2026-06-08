# Clark Refactor — Task List

## Foundations
- [x] utils/views.py — export `styled_view()` + `SectionView`
- [x] utils/__init__.py — re-export shared helpers

## Critical Bug Fixes
- [ ] cogs/logging.py — fix broken markdown (missing `**`), TTL cache, cog_load
- [ ] cogs/moderation.py — fix log_case race condition, cog_load, remove Colors
- [ ] cogs/tickets.py — fix 3x DB calls in create_ticket, transcript BytesIO, TicketConfigModal guard, populate active_tickets on cog_load
- [ ] cogs/selfroles.py — remove json.loads on JSONB, pass list directly, cog_load
- [ ] cogs/analytics.py — message batching, remove dead code/imports

## Pattern Cleanup (remove local Colors + _create_styled_view clones)
- [ ] cogs/verification.py — consolidate cog_load, remove double-init
- [ ] cogs/introduction.py — remove local Colors
- [ ] cogs/fun commands.py — remove local _create_container_view
- [ ] cogs/automod.py — remove local _create_styled_view
- [ ] cogs/ai responses.py — move setup_database to cog_load
- [ ] cogs/economy-underwork.py — confirm Colors import correct
- [ ] cogs/leveling.py — confirm Colors import correct

## Final
- [ ] git commit + push
