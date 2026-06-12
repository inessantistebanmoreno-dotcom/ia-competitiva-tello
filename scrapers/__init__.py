from scrapers.noel_scraper import NoelScraper
from scrapers.campofrio_scraper import CampofrioScraper
from scrapers.elpozo_scraper import ElPozoScraper
from scrapers.argal_scraper import ArgalScraper

SCRAPERS = {
    "noel":      NoelScraper,
    "campofrio": CampofrioScraper,
    "elpozo":    ElPozoScraper,
    "argal":     ArgalScraper,
}
