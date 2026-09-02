from django.core.management.base import BaseCommand

from riksdag.sync import CURRENT_TERM, sync_all


class Command(BaseCommand):
    help = "Hämta ledamöter och voteringar från Riksdagens öppna data."

    def add_arguments(self, parser):
        parser.add_argument(
            "--rm",
            action="append",
            dest="rms",
            help="Riksmöte att hämta, t.ex. 2025/26. Kan anges flera gånger. Standard: innevarande mandatperiod.",
        )

    def handle(self, *args, **options):
        rms = options["rms"] or CURRENT_TERM
        self.stdout.write(f"Synkar riksmöten: {', '.join(rms)}")
        sync_all(rms=rms, log=self.stdout.write)
