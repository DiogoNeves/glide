# SQLite, Git and synchronization

**Version the runtime source, schemas, tests and durable Markdown. Keep the live SQLite index outside the repository and ordinary file synchronization.** This is a Glide design choice for a rebuildable cache, not a claim that Git or SQLite cannot store or transfer a database.

SQLite warns that copying a changing database can mix old and new pages; pending recovery can also depend on the matching journal/WAL. Its backup API creates a consistent snapshot. A properly closed database can be copied safely, but an integrity check alone does not establish that a copied index contains the latest source revisions. See [SQLite copying guidance](https://sqlite.org/howtocorrupt.html#_backup_or_restore_while_a_transaction_is_active) and [backup API](https://sqlite.org/backup.html).

Git records files; its default binary merge behavior retains one side in the working tree and leaves a conflict for resolution. It does not merge SQLite transactions or rows. This makes concurrent edits to two synchronized database copies unsuitable for Glide's single-writer history. A completed immutable snapshot can still be transferred deliberately, with compatibility and source-head checks. Rebuilding is the default. See [Git binary merge behavior](https://git-scm.com/docs/gitattributes#_performing_a_three_way_merge).

The repository ignores the runtime's specific `index.sqlite3` filename and its journal files, Python caches and build artifacts. It deliberately does not ignore every `*.db`, `*.sqlite`, CSV or finance dataset: other projects may legitimately version reviewed synthetic fixtures or reference data. Production local state should remain physically outside the repository even when an ignore pattern exists.

`.gitignore` affects untracked files; it does not remove files already tracked. Before an upgrade, inspect `git ls-files` and `git status --short` for accidentally tracked state or credentials. Removing something from version control and scrubbing prior history are separate reviewed operations; do not silently rewrite history. See [gitignore](https://git-scm.com/docs/gitignore).

For Obsidian Sync, Markdown conflicts and non-Markdown conflicts behave differently; Sync is neither a transaction boundary nor a distributed lock. Keep one writer and wait for a complete bundle chain. Sync the readable memory and needed source evidence, install the runtime and skills separately per device, and rebuild the index. See [Obsidian Sync conflict handling](https://help.obsidian.md/sync/troubleshoot) and [Sync settings](https://help.obsidian.md/sync/settings).

No database is shipped in either Glide repository. The install/rebuild code creates its schema locally. [Upgrade and recovery](UPGRADING.md) includes machine transfer and rollback; protect private Markdown history and database snapshots according to the same data policy as their source material.
