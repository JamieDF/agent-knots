"""Policy rules — config toggles for the Settings screen.

Only the spend cap gets real enforcement (checked in the web server
before starting a new session, against the usage ledger). The rest are
configured but not yet enforced — there's no existing concept of a
migration file, a test-failure counter, or sudo-command detection to
hook into.
"""
