from scrapers.mistral_vision import extraer_nutricional_con_mistral
import json
from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth

stealth = Stealth()

with sync_playwright() as pw:
    browser = pw.chromium.launch(headless=False)
    context = browser.new_context()
    stealth.apply_stealth_sync(context)
    page = context.new_page()
    page.set_default_timeout(30000)
    
    page.goto('https://argal.com/productos/jamon-cocido-extra-bonnatur-finas-110g/', wait_until='domcontentloaded')
    page.wait_for_timeout(5000)
    
    img = page.screenshot(full_page=True)
    with open('screenshot_argal.png', 'wb') as f:
        f.write(img)
    print("Screenshot guardado")
    
    print("Enviando a Mistral Vision...")
    resultado = extraer_nutricional_con_mistral(img)
    print(json.dumps(resultado, ensure_ascii=False, indent=2))
    browser.close()