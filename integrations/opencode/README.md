# Tarkado OpenCode V2 connector (inactive source)

Server and terminal plugin implementation for explicit-task observe/shadow use.
No Laya, provider gateway, automatic model switching, prompt collection, or pilot
authority. No plugin/dependency is installed by this repository.

Read [the full scope, pairing, tests, and installation gates](../../docs/OPENCODE_CONNECTOR.md)
before loading into any session. Keep this directory outside automatic
`.opencode/plugins/` discovery until separately authorized.

```sh
node --test integrations/opencode/test/*.test.mjs
```

The controlled-host/core tests do not certify installed OpenCode/TUI compatibility.
The CLI entrypoint requires the compatible OpenCode-provided TUI/Solid runtime;
do not install peers or activate private sessions without operator approval.
