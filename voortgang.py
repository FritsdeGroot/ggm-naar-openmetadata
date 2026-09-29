#!/usr/bin/env python3
"""
Voortgangsindicatie voor lange laadruns (sinds v1.1.0).

- Uitvoer wordt per regel doorgegeven, ook bij `| tee` (Python buffert anders
  per 8 KB, waardoor een run minutenlang 'stil' lijkt).
- Fasen met tijdstempel en duur.
- Voortgangsprefix per objecttype: [ 123/947  13% | 05:12 | nog ~31m].
- Hartslag: is er `interval` seconden geen uitvoer geweest, dan volgt een
  regel met fase, voortgang, aantal API-aanroepen en een eventuele lopende
  aanroep die lang duurt. Zo is altijd zichtbaar dat het script nog leeft.
- API-meting: aantal aanroepen en gemiddelde duur per fase, plus een
  samenvatting aan het eind (waar gaat de tijd naartoe?).
- Standaard time-out op elke API-aanroep en automatische herhaling van
  GET-aanroepen bij tijdelijke fouten (502/503/504, verbroken verbinding),
  zodat een haperende server de run niet oneindig laat hangen.
"""

import sys
import threading
import time
from datetime import datetime
from urllib.parse import urlparse

from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

TIMEOUT = (10, 180)   # (verbinden, lezen) in seconden


def _duur(sec):
    sec = int(sec)
    h, rest = divmod(sec, 3600)
    m, s = divmod(rest, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


class _Uitvoer:
    """Wikkel om sys.stdout die bijhoudt wanneer er voor het laatst iets is geschreven."""

    def __init__(self, doel, voortgang):
        self._doel = doel
        self._v = voortgang

    def write(self, tekst):
        n = self._doel.write(tekst)
        if "\n" in tekst:
            self._doel.flush()
        self._v.laatste_uitvoer = time.monotonic()
        return n

    def flush(self):
        self._doel.flush()

    def __getattr__(self, naam):
        return getattr(self._doel, naam)


class Voortgang:
    def __init__(self, hartslag=60):
        self.start = time.monotonic()
        self.hartslag = hartslag
        self.laatste_uitvoer = time.monotonic()
        self.fase_naam = None
        self.fase_start = None
        self.fase_calls_start = 0
        self.fases = []            # (naam, duur, calls, api_tijd)
        self.totaal = 0
        self.gedaan = 0
        self.stap_start = None
        self.huidig = ""
        self.api_calls = 0
        self.api_tijd = 0.0
        self._fase_api_tijd_start = 0.0
        self.api_bezig = None      # (start, methode, pad)
        self._stop = threading.Event()

        sys.stdout = _Uitvoer(sys.stdout, self)
        sys.stderr = _Uitvoer(sys.stderr, self)
        threading.Thread(target=self._hartslag_lus, daemon=True).start()

    # --- fasen --------------------------------------------------------------
    def fase(self, naam, totaal=0):
        self._sluit_fase()
        self.fase_naam = naam
        self.fase_start = time.monotonic()
        self.fase_calls_start = self.api_calls
        self._fase_api_tijd_start = self.api_tijd
        self.totaal = totaal
        self.gedaan = 0
        self.stap_start = time.monotonic() if totaal else None
        print(f"[{datetime.now():%H:%M:%S}] ▶ {naam}"
              + (f" ({totaal} objecttypen)" if totaal else ""))

    def _sluit_fase(self):
        if self.fase_naam is None:
            return
        duur = time.monotonic() - self.fase_start
        self.fases.append((self.fase_naam, duur,
                           self.api_calls - self.fase_calls_start,
                           self.api_tijd - self._fase_api_tijd_start))
        self.fase_naam = None

    # --- stappen ------------------------------------------------------------
    def stap(self, omschrijving=""):
        """Markeer de start van het volgende objecttype."""
        self.gedaan += 1
        self.huidig = omschrijving

    def prefix(self):
        if not self.totaal:
            return ""
        pct = int(100 * self.gedaan / self.totaal)
        verstreken = time.monotonic() - self.stap_start
        eta = ""
        if self.gedaan >= 5:
            rest = verstreken / self.gedaan * (self.totaal - self.gedaan)
            eta = f" | nog ~{_duur(rest)}"
        return f"[{self.gedaan:>4}/{self.totaal} {pct:>3}% | {_duur(verstreken)}{eta}] "

    # --- API-meting ---------------------------------------------------------
    def api_start(self, methode, url):
        self.api_bezig = (time.monotonic(), methode, urlparse(url).path)

    def api_klaar(self, duur):
        self.api_calls += 1
        self.api_tijd += duur
        self.api_bezig = None

    # --- hartslag -----------------------------------------------------------
    def _hartslag_lus(self):
        while not self._stop.wait(5):
            if time.monotonic() - self.laatste_uitvoer < self.hartslag:
                continue
            delen = [f"[{datetime.now():%H:%M:%S}] … nog bezig",
                     f"fase: {self.fase_naam or '-'}"]
            if self.totaal:
                delen.append(f"{self.gedaan}/{self.totaal}")
            if self.huidig:
                delen.append(f"bij: {self.huidig}")
            delen.append(f"{self.api_calls} API-aanroepen")
            bezig = self.api_bezig
            if bezig and time.monotonic() - bezig[0] > 5:
                delen.append(f"wacht {int(time.monotonic() - bezig[0])}s op {bezig[1]} {bezig[2]}")
            print("  " + " | ".join(delen))

    # --- afsluiten ----------------------------------------------------------
    def samenvatting(self):
        self._sluit_fase()
        self._stop.set()
        totaal = time.monotonic() - self.start
        print(f"\nDuur per fase (totaal {_duur(totaal)}, {self.api_calls} API-aanroepen):")
        for naam, duur, calls, api_tijd in self.fases:
            gem = f", gem. {1000 * api_tijd / calls:.0f} ms" if calls else ""
            print(f"  {naam:<40} {_duur(duur):>8}  {calls:>6} aanroepen{gem}")


def instrumenteer_sessie(session, voortgang):
    """Meet elke API-aanroep, zet een standaard time-out en herhaal GET-aanroepen
    bij tijdelijke fouten. PATCH/POST/PUT/DELETE worden niet automatisch herhaald,
    om dubbele wijzigingen te voorkomen."""
    retry = Retry(total=3, connect=3, read=3, backoff_factor=2,
                  status_forcelist=(502, 503, 504), allowed_methods=frozenset({"GET"}),
                  raise_on_status=False)
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("http://", adapter)
    session.mount("https://", adapter)

    origineel = session.request

    def request(methode, url, **kwargs):
        kwargs.setdefault("timeout", TIMEOUT)
        voortgang.api_start(methode, url)
        t = time.monotonic()
        try:
            return origineel(methode, url, **kwargs)
        finally:
            voortgang.api_klaar(time.monotonic() - t)

    session.request = request
    return session
