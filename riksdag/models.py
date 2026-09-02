from django.db import models
from django.urls import reverse

from .parties import party_name


class Ledamot(models.Model):
    intressent_id = models.CharField(max_length=32, primary_key=True)
    sourceid = models.CharField(max_length=64, blank=True)
    tilltalsnamn = models.CharField(max_length=120)
    efternamn = models.CharField(max_length=120)
    sorteringsnamn = models.CharField(max_length=240, db_index=True)
    parti = models.CharField(max_length=8, db_index=True)
    valkrets = models.CharField(max_length=80, blank=True)
    status = models.CharField(max_length=160, blank=True)
    kon = models.CharField(max_length=16, blank=True)
    fodd_ar = models.PositiveIntegerField(null=True, blank=True)
    bild_url = models.URLField(blank=True)
    bild_url_liten = models.URLField(blank=True)
    epost = models.CharField(max_length=160, blank=True)
    titel = models.CharField(max_length=160, blank=True)
    is_current = models.BooleanField(default=False, db_index=True)
    antal_voteringar = models.PositiveIntegerField(default=0)
    antal_franvarande = models.PositiveIntegerField(default=0)
    antal_med_partiet = models.PositiveIntegerField(default=0)
    antal_mot_partiet = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["sorteringsnamn"]

    def __str__(self):
        return self.namn

    @property
    def namn(self):
        return f"{self.tilltalsnamn} {self.efternamn}".strip()

    @property
    def parti_namn(self):
        return party_name(self.parti)

    @property
    def narvaro_pct(self):
        if not self.antal_voteringar:
            return None
        present = self.antal_voteringar - self.antal_franvarande
        return round(100 * present / self.antal_voteringar, 1)

    @property
    def franvaro_pct(self):
        if not self.antal_voteringar:
            return None
        return round(100 * self.antal_franvarande / self.antal_voteringar, 1)

    @property
    def partilinje_pct(self):
        compared = self.antal_med_partiet + self.antal_mot_partiet
        if not compared:
            return None
        return round(100 * self.antal_med_partiet / compared, 1)

    @property
    def riksdagen_url(self):
        if not self.sourceid:
            return ""
        return f"https://www.riksdagen.se/sv/ledamoter-partier/ledamot/_{self.sourceid}"

    def get_absolute_url(self):
        return reverse("ledamot_detail", args=[self.intressent_id])


class Uppdrag(models.Model):
    ledamot = models.ForeignKey(Ledamot, related_name="uppdrag", on_delete=models.CASCADE)
    organ_kod = models.CharField(max_length=32)
    organ_namn = models.CharField(max_length=160, blank=True)
    roll = models.CharField(max_length=80)
    typ = models.CharField(max_length=40, blank=True)
    from_date = models.DateField(null=True, blank=True)
    to_date = models.DateField(null=True, blank=True)
    is_current = models.BooleanField(default=False)

    class Meta:
        ordering = ["organ_kod", "roll"]


class Betankande(models.Model):
    dok_id = models.CharField(max_length=32, primary_key=True)
    rm = models.CharField(max_length=16, db_index=True)
    beteckning = models.CharField(max_length=32, db_index=True)
    titel = models.CharField(max_length=400, blank=True)
    organ = models.CharField(max_length=16, blank=True)
    datum = models.DateField(null=True, blank=True)
    notis = models.TextField(blank=True)

    def __str__(self):
        return f"{self.rm}:{self.beteckning}"


class Votering(models.Model):
    votering_id = models.CharField(max_length=64, primary_key=True)
    rm = models.CharField(max_length=16, db_index=True)
    beteckning = models.CharField(max_length=32, db_index=True)
    punkt = models.PositiveIntegerField(default=1)
    dok_id = models.CharField(max_length=32, blank=True, db_index=True)
    datum = models.DateField(null=True, blank=True, db_index=True)
    avser = models.CharField(max_length=40, blank=True)
    titel = models.CharField(max_length=400, blank=True)
    ja = models.PositiveIntegerField(default=0)
    nej = models.PositiveIntegerField(default=0)
    avstar = models.PositiveIntegerField(default=0)
    franvarande = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["-datum", "beteckning", "punkt"]

    def __str__(self):
        return f"{self.rm} {self.beteckning} p{self.punkt}"

    @property
    def rubrik(self):
        return self.titel or f"Betänkande {self.beteckning}"

    @property
    def beslut(self):
        tallies = {"Ja": self.ja, "Nej": self.nej, "Avstår": self.avstar}
        winner = max(tallies, key=tallies.get)
        if tallies[winner] == 0:
            return ""
        return winner

    def get_absolute_url(self):
        return reverse("votering_detail", args=[self.votering_id])


class Rost(models.Model):
    votering = models.ForeignKey(Votering, related_name="roster", on_delete=models.CASCADE)
    ledamot = models.ForeignKey(
        Ledamot, related_name="roster", null=True, blank=True, on_delete=models.SET_NULL
    )
    intressent_id = models.CharField(max_length=32, db_index=True)
    namn = models.CharField(max_length=160)
    parti = models.CharField(max_length=8, db_index=True)
    rost = models.CharField(max_length=16)
    med_partiet = models.BooleanField(null=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["votering", "intressent_id"], name="unique_rost")
        ]
        indexes = [
            models.Index(fields=["ledamot", "rost"]),
            models.Index(fields=["votering", "parti"]),
        ]

    def __str__(self):
        return f"{self.namn}: {self.rost}"


class PartiLinje(models.Model):
    votering = models.ForeignKey(Votering, related_name="partilinjer", on_delete=models.CASCADE)
    parti = models.CharField(max_length=8)
    linje = models.CharField(max_length=16, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["votering", "parti"], name="unique_partilinje")
        ]
