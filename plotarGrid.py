"""
Visualizador do Grid IBGE 1km² — Cataguases/MG
===============================================
Gera UM mapa interativo com:
  - Contorno do município de Cataguases
  - 3 camadas alternáveis: População / Domicílios / Bairros
  - Tooltips com dados ao passar o mouse
  - Legenda dinâmica por camada

Pré-requisitos:
    pip install folium pandas geopandas requests

Arquivos necessários:
    dados/grade_cataguases.csv
    dados/BR_Municipios_2022/BR_Municipios_2022.shp

Uso:
    python plotar_grid_cataguases.py

Saída:
    dados/mapa_cataguases.html
"""

import webbrowser
import hashlib
import colorsys
import json
import requests
import pandas as pd
import geopandas as gpd
import folium
from folium import LayerControl, GeoJson, GeoJsonTooltip
from pathlib import Path

# ══════════════════════════════════════════════════════
#  CAMINHOS E CONSTANTES
# ══════════════════════════════════════════════════════

BASE           = Path(__file__).parent
DADOS          = BASE / "dados"
CSV_PATH       = DADOS / "grade_cataguases.csv"
MUNICIPIOS_SHP = DADOS / "BR_Municipios_2022" / "BR_Municipios_2022.shp"
OUTPUT_HTML    = DADOS / "mapa_cataguases.html"

COD_MUNICIPIO  = "3115300"
CRS_METRICO    = "EPSG:31983"
DELTA          = 0.0045   # metade do lado da célula em graus (~500m)

# ══════════════════════════════════════════════════════
#  CARREGA DADOS
# ══════════════════════════════════════════════════════

print("=" * 55)
print(" Visualizador Grid IBGE — Cataguases/MG")
print("=" * 55)

if not CSV_PATH.exists():
    raise FileNotFoundError(f"CSV não encontrado: {CSV_PATH}\nRode primeiro gerar_grid_cataguases.py")

df = pd.read_csv(CSV_PATH)
print(f"\n  Células : {len(df):,}")
print(f"  Pop.    : {df['populacao'].sum():,}")
print(f"  Dom.    : {df['domicilios'].sum():,}")
print(f"  Bairros : {df['bairro'].nunique()}")

centro_lat = df["lat_centroide"].mean()
centro_lon = df["lon_centroide"].mean()

# ══════════════════════════════════════════════════════
#  CARREGA LIMITE DO MUNICÍPIO
# ══════════════════════════════════════════════════════

print("\n  Carregando limite do município...")
municipios = gpd.read_file(MUNICIPIOS_SHP)
municipios.columns = municipios.columns.str.upper()
if "GEOMETRY" in municipios.columns:
    municipios = municipios.set_geometry("GEOMETRY")

cod_col = next(
    c for c in municipios.columns
    if c in ("CD_MUN", "CD_GEOCMU", "COD_MUN", "GEOCODIGO", "CD_MUNICIPIO")
)
cataguases_gdf = municipios[
    municipios[cod_col].astype(str).str[:7] == COD_MUNICIPIO
].to_crs("EPSG:4326")

limite_geojson = json.loads(cataguases_gdf.geometry.to_json())
print("  ✓ Limite carregado")

# ══════════════════════════════════════════════════════
#  FUNÇÕES DE COR
# ══════════════════════════════════════════════════════

def valor_para_cor(valor, vmin, vmax):
    """Gradiente azul claro → laranja → vermelho escuro."""
    t = (valor - vmin) / (vmax - vmin) if vmax != vmin else 0.5
    t = max(0.0, min(1.0, t))
    if t < 0.5:
        s = t * 2
        r = int(224 + (247 - 224) * s)
        g = int(243 + (163 - 243) * s)
        b = int(255 + ( 71 - 255) * s)
    else:
        s = (t - 0.5) * 2
        r = int(247 + (178 - 247) * s)
        g = int(163 + (  0 - 163) * s)
        b = int( 71 + (  0 -  71) * s)
    return f"#{r:02x}{g:02x}{b:02x}"

def bairro_para_cor(nome):
    h = int(hashlib.md5(nome.encode()).hexdigest(), 16) % 360
    r, g, b = colorsys.hls_to_rgb(h / 360, 0.52, 0.72)
    return f"#{int(r*255):02x}{int(g*255):02x}{int(b*255):02x}"

# ══════════════════════════════════════════════════════
#  MONTA O MAPA BASE
# ══════════════════════════════════════════════════════

print("\n  Montando mapa...")

mapa = folium.Map(
    location=[centro_lat, centro_lon],
    zoom_start=12,
    tiles="CartoDB positron",
)

# ── Limite do município ────────────────────────────────
folium.GeoJson(
    limite_geojson,
    name="Limite de Cataguases",
    style_function=lambda _: {
        "color"       : "#1a1a2e",
        "weight"      : 2.5,
        "fillColor"   : "transparent",
        "fillOpacity" : 0,
    },
    tooltip=folium.Tooltip("Cataguases — Município", sticky=False),
).add_to(mapa)

# ══════════════════════════════════════════════════════
#  CAMADA 1 — POPULAÇÃO
# ══════════════════════════════════════════════════════

pop_min = int(df["populacao"].min())
pop_max = int(df["populacao"].max())

layer_pop = folium.FeatureGroup(name="🟠 População", show=True)

for _, row in df.iterrows():
    cor = valor_para_cor(row["populacao"], pop_min, pop_max)
    tip = (
        f"<div style='font-family:Segoe UI,sans-serif;font-size:13px;min-width:170px'>"
        f"<b style='font-size:14px'>{row['bairro']}</b><br>"
        f"<hr style='margin:4px 0;border-color:#eee'>"
        f"👥 <b>População:</b> {int(row['populacao']):,}<br>"
        f"🏠 Domicílios: {int(row['domicilios']):,}<br>"
        f"📐 Área: {row['area_km2']:.2f} km²<br>"
        f"<span style='color:#999;font-size:11px'>"
        f"{row['lat_centroide']:.4f}, {row['lon_centroide']:.4f}</span>"
        f"</div>"
    )
    folium.Rectangle(
        bounds=[
            [row["lat_centroide"] - DELTA, row["lon_centroide"] - DELTA],
            [row["lat_centroide"] + DELTA, row["lon_centroide"] + DELTA],
        ],
        color="#fff",
        weight=0.4,
        fill=True,
        fill_color=cor,
        fill_opacity=0.78,
        tooltip=folium.Tooltip(tip, sticky=True),
    ).add_to(layer_pop)

layer_pop.add_to(mapa)

# ══════════════════════════════════════════════════════
#  CAMADA 2 — DOMICÍLIOS
# ══════════════════════════════════════════════════════

dom_min = int(df["domicilios"].min())
dom_max = int(df["domicilios"].max())

layer_dom = folium.FeatureGroup(name="🔵 Domicílios", show=False)

for _, row in df.iterrows():
    cor = valor_para_cor(row["domicilios"], dom_min, dom_max)
    tip = (
        f"<div style='font-family:Segoe UI,sans-serif;font-size:13px;min-width:170px'>"
        f"<b style='font-size:14px'>{row['bairro']}</b><br>"
        f"<hr style='margin:4px 0;border-color:#eee'>"
        f"🏠 <b>Domicílios:</b> {int(row['domicilios']):,}<br>"
        f"👥 População: {int(row['populacao']):,}<br>"
        f"📐 Área: {row['area_km2']:.2f} km²<br>"
        f"<span style='color:#999;font-size:11px'>"
        f"{row['lat_centroide']:.4f}, {row['lon_centroide']:.4f}</span>"
        f"</div>"
    )
    folium.Rectangle(
        bounds=[
            [row["lat_centroide"] - DELTA, row["lon_centroide"] - DELTA],
            [row["lat_centroide"] + DELTA, row["lon_centroide"] + DELTA],
        ],
        color="#fff",
        weight=0.4,
        fill=True,
        fill_color=cor,
        fill_opacity=0.78,
        tooltip=folium.Tooltip(tip, sticky=True),
    ).add_to(layer_dom)

layer_dom.add_to(mapa)

# ══════════════════════════════════════════════════════
#  CAMADA 3 — BAIRROS
# ══════════════════════════════════════════════════════

bairros_unicos = sorted(df["bairro"].unique())
cores_bairros  = {b: bairro_para_cor(b) for b in bairros_unicos}

layer_bai = folium.FeatureGroup(name="🏘️ Bairros", show=False)

for _, row in df.iterrows():
    cor = cores_bairros[row["bairro"]]
    tip = (
        f"<div style='font-family:Segoe UI,sans-serif;font-size:13px;min-width:170px'>"
        f"<b style='font-size:14px'>{row['bairro']}</b><br>"
        f"<hr style='margin:4px 0;border-color:#eee'>"
        f"👥 População: {int(row['populacao']):,}<br>"
        f"🏠 Domicílios: {int(row['domicilios']):,}<br>"
        f"📐 Área: {row['area_km2']:.2f} km²<br>"
        f"<span style='color:#999;font-size:11px'>"
        f"{row['lat_centroide']:.4f}, {row['lon_centroide']:.4f}</span>"
        f"</div>"
    )
    folium.Rectangle(
        bounds=[
            [row["lat_centroide"] - DELTA, row["lon_centroide"] - DELTA],
            [row["lat_centroide"] + DELTA, row["lon_centroide"] + DELTA],
        ],
        color="#fff",
        weight=0.4,
        fill=True,
        fill_color=cor,
        fill_opacity=0.82,
        tooltip=folium.Tooltip(tip, sticky=True),
    ).add_to(layer_bai)

layer_bai.add_to(mapa)

# ══════════════════════════════════════════════════════
#  CONTROLE DE CAMADAS
# ══════════════════════════════════════════════════════

folium.LayerControl(collapsed=False, position="topright").add_to(mapa)

# ══════════════════════════════════════════════════════
#  LEGENDAS DINÂMICAS (via JavaScript — troca conforme layer ativa)
# ══════════════════════════════════════════════════════

# Legenda gradiente para pop e dom
def gradiente_html(titulo, vmin, vmax):
    return (
        f"<b style='font-size:13px'>{titulo}</b><br>"
        f"<div style='display:flex;align-items:center;gap:6px;margin-top:6px'>"
        f"<span style='font-size:11px;color:#555'>{vmin:,}</span>"
        f"<div style='flex:1;height:13px;border-radius:4px;"
        f"background:linear-gradient(to right,#e0f3ff,#f7a347,#b20000)'></div>"
        f"<span style='font-size:11px;color:#555'>{vmax:,}</span>"
        f"</div>"
    )

bairros_legenda = "".join(
    f"<div style='display:flex;align-items:center;gap:5px;margin:2px 0'>"
    f"<div style='width:12px;height:12px;border-radius:2px;background:{cores_bairros[b]};flex-shrink:0'></div>"
    f"<span style='font-size:11px;color:#333'>{b}</span></div>"
    for b in bairros_unicos
)

legenda_js = f"""
<div id="legenda-box" style="
    position:fixed; bottom:36px; left:16px; z-index:9999;
    background:rgba(255,255,255,0.93); padding:14px 16px;
    border-radius:10px; box-shadow:0 2px 14px rgba(0,0,0,0.18);
    font-family:'Segoe UI',sans-serif; min-width:190px; max-width:210px;
    max-height:340px; overflow-y:auto;">
    <div id="legenda-conteudo"></div>
</div>

<script>
var legendaPopHtml  = `{gradiente_html('👥 População', pop_min, pop_max)}`;
var legendaDomHtml  = `{gradiente_html('🏠 Domicílios', dom_min, dom_max)}`;
var legendaBaiHtml  = `<b style='font-size:13px'>🏘️ Bairros</b><br><div style='margin-top:6px'>{bairros_legenda}</div>`;

function atualizarLegenda() {{
    var conteudo = document.getElementById('legenda-conteudo');
    var checkboxes = document.querySelectorAll('.leaflet-control-layers-overlays input[type=checkbox]');
    var labels     = document.querySelectorAll('.leaflet-control-layers-overlays label span');
    var html = '';
    checkboxes.forEach(function(cb, i) {{
        if (!cb.checked) return;
        var label = labels[i] ? labels[i].textContent.trim() : '';
        if (label.includes('opula'))  html = legendaPopHtml;
        if (label.includes('omic'))   html = legendaDomHtml;
        if (label.includes('airro'))  html = legendaBaiHtml;
    }});
    if (conteudo) conteudo.innerHTML = html || legendaPopHtml;
}}

// Aguarda o mapa carregar antes de registrar eventos
setTimeout(function() {{
    document.querySelectorAll('.leaflet-control-layers-overlays input').forEach(function(cb) {{
        cb.addEventListener('change', atualizarLegenda);
    }});
    atualizarLegenda();
}}, 800);
</script>
"""

mapa.get_root().html.add_child(folium.Element(legenda_js))

# ── Título ─────────────────────────────────────────────
titulo_html = """
<div style="
    position:fixed; top:14px; left:50%; transform:translateX(-50%);
    z-index:9999; background:rgba(255,255,255,0.93);
    padding:8px 24px; border-radius:8px;
    box-shadow:0 2px 10px rgba(0,0,0,0.15);
    font-family:'Segoe UI',sans-serif;
    font-weight:700; font-size:15px; color:#1a1a2e; white-space:nowrap;">
    Grade Estatística IBGE 1km² — Cataguases / MG
</div>
"""
mapa.get_root().html.add_child(folium.Element(titulo_html))

# ══════════════════════════════════════════════════════
#  SALVA E ABRE
# ══════════════════════════════════════════════════════

mapa.save(OUTPUT_HTML)

print(f"\n{'═'*55}")
print(f"  ✅  Mapa salvo em: dados/mapa_cataguases.html")
print(f"{'═'*55}")

webbrowser.open(OUTPUT_HTML.resolve().as_uri())