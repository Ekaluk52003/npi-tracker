"""
core/management/commands/poll_onedrive.py
==========================================
Management command: poll OneDrive inbound folder and run emails through AI agent.

USAGE:
    python manage.py poll_onedrive                          # run once
    python manage.py poll_onedrive --dry-run                # preview, no DB changes
    python manage.py poll_onedrive --file email_001.json    # single file
    python manage.py poll_onedrive --loop                   # repeat every 5 min (default)
    python manage.py poll_onedrive --loop --interval 60     # repeat every 60 seconds
"""
import time
from django.core.management.base import BaseCommand
from django.conf import settings
from django.utils import timezone


class Command(BaseCommand):
    help = "Poll OneDrive NPI-Queue/inbound and process email JSON files through AI agent"

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Read and analyse files but make no DB changes and do not move files",
        )
        parser.add_argument(
            "--file",
            type=str,
            default=None,
            metavar="FILENAME",
            help="Process a single named file from the inbound folder",
        )
        parser.add_argument(
            "--loop",
            action="store_true",
            help="Keep running and poll repeatedly until Ctrl+C",
        )
        parser.add_argument(
            "--interval",
            type=int,
            default=300,
            metavar="SECONDS",
            help="Seconds between polls when using --loop (default: 300 = 5 min)",
        )

    def handle(self, *args, **options):
        if not getattr(settings, "AI_AGENT_ENABLED", False):
            self.stdout.write(
                self.style.WARNING(
                    "AI_AGENT_ENABLED=False in .env — set it to True to enable the agent"
                )
            )
            return

        dry_run     = options["dry_run"]
        single_file = options.get("file")
        loop        = options["loop"]
        interval    = options["interval"]

        if dry_run:
            self.stdout.write(self.style.WARNING("DRY RUN — no changes will be made"))

        if loop:
            self.stdout.write(
                self.style.SUCCESS(f"Loop mode — polling every {interval}s. Press Ctrl+C to stop.\n")
            )
            try:
                while True:
                    self._run_once(single_file, dry_run)
                    self.stdout.write(f"  Next poll in {interval}s  ({timezone.now().strftime('%H:%M:%S')})\n")
                    time.sleep(interval)
            except KeyboardInterrupt:
                self.stdout.write("\nStopped.")
        else:
            self._run_once(single_file, dry_run)

    # ── helpers ──────────────────────────────────────────────────────────

    def _run_once(self, single_file, dry_run):
        if single_file:
            self._process_single(single_file, dry_run)
        else:
            self._process_queue(dry_run)

    def _process_single(self, filename, dry_run):
        from services.email_queue import process_single_file

        self.stdout.write(f"Processing single file: {filename}")
        try:
            result = process_single_file(filename, dry_run=dry_run)
        except Exception as exc:
            self.stdout.write(self.style.ERROR(f"ERROR: {exc}"))
            return

        if result.get("dry_run"):
            self.stdout.write(self.style.SUCCESS(f"Project: {result['project']}"))
            self.stdout.write("AI prompt that would be sent:")
            self.stdout.write(result.get("ai_prompt", "(none)"))
        else:
            self.stdout.write(self.style.SUCCESS(f"Project: {result.get('project')}"))
            for action in result.get("actions", []):
                if action.get("error"):
                    self.stdout.write(self.style.ERROR(f"  Action FAILED: {action}"))
                else:
                    self.stdout.write(self.style.SUCCESS(f"  Action OK: {action}"))

    def _process_queue(self, dry_run):
        from services.email_queue import process_inbound_queue

        self.stdout.write(f"Checking OneDrive inbound folder...  [{timezone.now().strftime('%H:%M:%S')}]")
        try:
            results = process_inbound_queue(dry_run=dry_run)
        except Exception as exc:
            self.stdout.write(self.style.ERROR(f"Pipeline error: {exc}"))
            return

        if not results:
            self.stdout.write("  No new files.")
            return

        ok = err = 0
        for r in results:
            fname = r.get("filename", "?")
            if r.get("error"):
                self.stdout.write(self.style.ERROR(f"  ERROR  {fname}: {r['error']}"))
                err += 1
            else:
                n     = len(r.get("actions", []))
                proj  = r.get("project", "unknown project")
                moved = "" if r.get("moved", True) else " (move failed)"
                self.stdout.write(
                    self.style.SUCCESS(f"  OK     {fname} → {proj} — {n} action(s){moved}")
                )
                ok += 1

        self.stdout.write(f"  Done: {ok} OK, {err} error(s) out of {len(results)} file(s)")
