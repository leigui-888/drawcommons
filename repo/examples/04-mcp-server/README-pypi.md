<!-- mcp-name: io.github.leigui-888/drawcommons-ledger -->

# drawcommons-ledger-mcp

**Read-only** MCP server for a public audit ledger. Zero dependencies (Python standard
library only, stdio transport). No accounts, no API keys, no write path.

> **Beta.** This ledger currently holds test data, not real records. The `instructions`
> block sent at handshake is built **at that moment** from the live site: it states how many
> entries exist and quotes the site's own `data_notice` about what that data is. If the
> fetch fails, it asserts no number at all. Protocol version and its comment status are not
> hardcoded here — a version string written into a package goes stale, and a stale version
> string is worse than none: see <https://drawcommons.org/terms>.

## Run

```bash
uvx drawcommons-ledger-mcp                  # or: pip install drawcommons-ledger-mcp
```

Client configuration (Claude Desktop / Cursor / Claude Code):

```json
{
  "mcpServers": {
    "ledger": {
      "command": "uvx",
      "args": ["drawcommons-ledger-mcp"]
    }
  }
}
```

Point it at another deployment with `--base https://your-host` (or `LEDGER_BASE`).

## Tools

| tool | returns |
|---|---|
| `ledger_items` | entries (paginated, filterable by type), each with `prev_hash` / `hash` |
| `ledger_verify` | `verdict` + the server's own claim + **recomputation done locally** + anchor |
| `ledger_export` | the exported bytes' sha256 (the anchor), byte count, optionally the raw text |

`ledger_verify` does not trust the server's `ok`. It fetches the entries and the export,
recomputes `sha256(prev_hash + "\n" + canonical(entry))` for every entry on the calling
machine, checks that each `prev_hash` links to the previous `hash`, and recomputes the
anchor from the exported bytes. Verdicts: `agree`, `chain_broken` (with the first bad
index), `server_disagrees` (the server's own numbers contradict the entries it served).

A tool that merely repeats the upstream conclusion turns an upstream error into
"verified". That is the one thing this package exists to avoid.

## Boundaries

1. **Read-only, one address.** The base URL is fixed at launch; tool arguments cannot
   change it (otherwise the server becomes an open proxy on the caller's machine).
2. **Bytes, not facts.** A complete hash chain only proves the bytes you fetched match
   what was chained. Someone can record a false entry honestly, and the chain stays valid.
3. **Beta.** Fields may change with the ledger version, which is why no `outputSchema` is
   declared: declaring one would promise the fields never grow or shrink.

Source, tests and the Chinese-language docs:
<https://github.com/leigui-888/drawcommons/tree/main/repo/examples/04-mcp-server>

## License

Apache-2.0 (full text: <https://github.com/leigui-888/drawcommons/blob/main/repo/LICENSE>).
The data the API returns is CC-BY-4.0: attribution required, commercial use allowed.
