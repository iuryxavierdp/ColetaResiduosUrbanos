"""
Grade Estatística IBGE 1km² — Cataguases/MG
============================================
Estrutura esperada:
    pesquisaIF/
    ├── gerar_grid_cataguases.py   ← este arquivo
    └── dados/
        ├── BR_Municipios_2022/
        │   └── BR_Municipios_2022.shp  (+ .dbf, .prj, .shx)
        └── BR1KM_20251002/
            └── BR1KM_20251002.shp      (+ .dbf, .prj, .shx)

Instalação:
    pip install geopandas pandas shapely requests

Uso:
    python gerar_grid_cataguases.py

Saída:
    dados/grade_cataguases.csv  (todo o município: urbano + rural)
    dados/_cache_bairros.csv    (cache OSM para re-execuções rápidas)
"""

import time
import geopandas as gpd
import pandas as pd
import requests
from pathlib import Path

# ══════════════════════════════════════════════════════
#  CAMINHOS
# ══════════════════════════════════════════════════════

BASE           = Path(__file__).parent
DADOS          = BASE / "dados"
GRADE_SHP      = DADOS / "BR1KM_20251002"     / "BR1KM_20251002.shp"
MUNICIPIOS_SHP = DADOS / "BR_Municipios_2022" / "BR_Municipios_2022.shp"
OUTPUT_CSV     = DADOS / "grade_cataguases.csv"
CACHE_CSV      = DADOS / "_cache_bairros.csv"   # evita re-consultar o OSM

# ══════════════════════════════════════════════════════
#  CONSTANTES
# ══════════════════════════════════════════════════════

MUNICIPIO_NOME = "Cataguases"
COD_MUNICIPIO  = "3115300"
CRS_METRICO    = "EPSG:31983"   # SIRGAS 2000 / UTM zona 23S

# ══════════════════════════════════════════════════════
#  VALIDAÇÃO DOS ARQUIVOS
# ══════════════════════════════════════════════════════

for p in [GRADE_SHP, MUNICIPIOS_SHP]:
    if not p.exists():
        pasta = p.parent
        shps = list(pasta.glob("*.shp"))
        if shps:
            print(f"  Aviso: '{p.name}' não encontrado. Usando '{shps[0].name}'.")
            if "Municipio" in str(p):
                MUNICIPIOS_SHP = shps[0]
            else:
                GRADE_SHP = shps[0]
        else:
            raise FileNotFoundError(
                f"\nArquivo não encontrado: {p}\n"
                f"Verifique se a pasta '{pasta}' contém um .shp."
            )

# ══════════════════════════════════════════════════════
#  1. MUNICÍPIO — polígono de Cataguases
# ══════════════════════════════════════════════════════

print("=" * 55)
print(" Grade Estatística IBGE 1km² — Cataguases/MG")
print("=" * 55)

print("\n[1/5] Carregando municípios...")
municipios = gpd.read_file(MUNICIPIOS_SHP)
municipios.columns = municipios.columns.str.upper()
if "GEOMETRY" in municipios.columns:
    municipios = municipios.set_geometry("GEOMETRY")

cod_col = next(
    (c for c in municipios.columns
     if c in ("CD_MUN", "CD_GEOCMU", "COD_MUN", "GEOCODIGO", "CD_MUNICIPIO")),
    None
)
if cod_col is None:
    raise ValueError(f"Coluna de código do município não encontrada. Colunas: {list(municipios.columns)}")

cataguases = municipios[
    municipios[cod_col].astype(str).str[:7] == COD_MUNICIPIO
].copy()

if cataguases.empty:
    raise ValueError(f"Município {MUNICIPIO_NOME} (cód. {COD_MUNICIPIO}) não encontrado.")

print(f"  ✓ {MUNICIPIO_NOME} encontrado  |  CRS: {cataguases.crs}")

# ══════════════════════════════════════════════════════
#  2. GRADE — recorte pelo município completo (urbano + rural)
#     + classificação de zona via perímetro urbano do OSM
# ══════════════════════════════════════════════════════

import json as _json
from shapely.geometry import box as _box, Polygon as _Poly
from shapely.ops import unary_union as _unary_union

print("\n[2/5] Carregando grade 1km² para o município inteiro...")

grade = gpd.read_file(GRADE_SHP, bbox=tuple(cataguases.total_bounds))
grade.columns = grade.columns.str.upper()
if "GEOMETRY" in grade.columns:
    grade = grade.set_geometry("GEOMETRY")
print(f"  Células na bounding box: {len(grade):,}")

# Alinhar CRS
if grade.crs != cataguases.crs:
    cataguases = cataguases.to_crs(grade.crs)

# Filtro pelo centróide dentro do polígono do município
poligono_municipio = cataguases.union_all()
centroides_raw     = grade.geometry.centroid
grade_cat          = grade[centroides_raw.within(poligono_municipio)].copy()
print(f"  ✓ Células no município de {MUNICIPIO_NOME}: {len(grade_cat):,}")

if grade_cat.empty:
    raise ValueError("Nenhuma célula encontrada. Verifique os CRS dos shapefiles.")

# ── Classificação urbana/rural via perímetro OSM (Overpass) ───────────────────
print("\n  Buscando perímetro urbano no OSM para classificar zona...")

OVERPASS_URL   = "https://overpass-api.de/api/interpreter"
OVERPASS_QUERY = """
[out:json][timeout:30];
(
  relation["name"="Cataguases"]["place"="city"];
  relation["name"="Cataguases"]["boundary"="administrative"]["admin_level"="8"];
  way["name"="Cataguases"]["place"="city"];
);
out geom;
"""
BBOX_URBANA = _box(-42.74, -21.42, -42.65, -21.34)   # fallback

poligono_urbano = None
try:
    resp      = __import__("requests").post(OVERPASS_URL, data={"data": OVERPASS_QUERY}, timeout=30)
    resp.raise_for_status()
    elementos = resp.json().get("elements", [])
    poligonos = []
    for el in elementos:
        if el.get("type") == "relation":
            for m in el.get("members", []):
                if m.get("type") == "way" and m.get("role") in ("outer", ""):
                    coords = [(n["lon"], n["lat"]) for n in m.get("geometry", [])]
                    if len(coords) >= 3:
                        poligonos.append(_Poly(coords))
        elif el.get("type") == "way":
            coords = [(n["lon"], n["lat"]) for n in el.get("geometry", [])]
            if len(coords) >= 3:
                poligonos.append(_Poly(coords))
    if poligonos:
        poligono_urbano = _unary_union(poligonos)
        print(f"  ✓ Perímetro urbano OSM obtido ({len(poligonos)} polígono(s))")
except Exception as e:
    print(f"  Aviso: OSM falhou ({e}). Usando bounding box de fallback.")

if poligono_urbano is None or poligono_urbano.is_empty:
    poligono_urbano = BBOX_URBANA
    print("  Usando bounding box urbana padrão.")

# CRS da grade para o polígono urbano
urbano_gdf = gpd.GeoDataFrame(geometry=[poligono_urbano], crs="EPSG:4326")
if urbano_gdf.crs != grade_cat.crs:
    urbano_gdf = urbano_gdf.to_crs(grade_cat.crs)
pol_urbano_alinhado = urbano_gdf.union_all()

# Classifica cada célula como urbana ou rural pelo centróide
centroides_cat = grade_cat.geometry.centroid
grade_cat      = grade_cat.copy()
grade_cat["zona"] = centroides_cat.within(pol_urbano_alinhado).map(
    {True: "urbana", False: "rural"}
)
n_urb = (grade_cat["zona"] == "urbana").sum()
n_rur = (grade_cat["zona"] == "rural").sum()
print(f"  ✓ Células urbanas: {n_urb}  |  rurais: {n_rur}")

# ══════════════════════════════════════════════════════
#  3. CENTRÓIDES em lat/lon (WGS84)
# ══════════════════════════════════════════════════════

print("\n[3/5] Calculando centróides...")

grade_m      = grade_cat.to_crs(CRS_METRICO)
centroides_m = grade_m.geometry.centroid

centroides_geo = gpd.GeoDataFrame(
    geometry=centroides_m, crs=CRS_METRICO
).to_crs("EPSG:4326")

grade_cat = grade_cat.copy()
grade_cat["lat_centroide"] = centroides_geo.geometry.y.values
grade_cat["lon_centroide"] = centroides_geo.geometry.x.values
grade_cat["area_km2"]      = (grade_m.geometry.area / 1_000_000).round(4).values
print("  ✓ Centróides calculados")

# ══════════════════════════════════════════════════════
#  4. BAIRROS — via OpenStreetMap (Nominatim reverse geocoding)
# ══════════════════════════════════════════════════════

print("\n[4/5] Buscando nomes de bairros via OpenStreetMap...")
print("  (1 consulta por célula com ~1s de intervalo — respeita limite da API)")
print("  Na 2ª execução em diante usa cache local e termina instantaneamente.\n")

# Carrega cache existente (evita repetir consultas ao Nominatim)
cache = {}
if CACHE_CSV.exists():
    try:
        df_c = pd.read_csv(CACHE_CSV, dtype=str)
        for _, row in df_c.iterrows():
            k = (round(float(row["lat"]), 6), round(float(row["lon"]), 6))
            cache[k] = row["bairro"]
        print(f"  Cache carregado: {len(cache)} entradas")
    except Exception as e:
        print(f"  Aviso: não foi possível ler cache ({e}). Consultando do zero.")
        cache = {}

HEADERS = {"User-Agent": "pesquisaIF-cataguases/1.0 (estudo academico)"}

def reverse_geocode_bairro(lat: float, lon: float) -> str:
    """
    Consulta o Nominatim e retorna o nome do bairro.
    Prioridade dos campos OSM:
        suburb → quarter → neighbourhood → village → city_district → town
    """
    key = (round(lat, 6), round(lon, 6))
    if key in cache:
        return cache[key]          # usa cache, sem delay

    url    = "https://nominatim.openstreetmap.org/reverse"
    params = {"lat": lat, "lon": lon, "format": "jsonv2",
              "zoom": 18, "addressdetails": 1}
    try:
        r    = requests.get(url, params=params, headers=HEADERS, timeout=10)
        r.raise_for_status()
        addr = r.json().get("address", {})
        bairro = (
            addr.get("neighbourhood")   # bairro urbano mais específico
            or addr.get("suburb")       # subúrbio / bairro
            or addr.get("quarter")      # setor / quarteirão
            or addr.get("hamlet")       # localidade rural pequena
            or addr.get("village")      # vila / distrito rural
            or addr.get("city_district")
            or addr.get("town")
            or "N/D"
        )
    except Exception as e:
        bairro = "N/D"

    cache[key] = bairro
    time.sleep(1.1)    # Nominatim: máx. 1 req/s por política de uso
    return bairro

bairros = []
total   = len(grade_cat)
for i, (_, row) in enumerate(grade_cat.iterrows(), 1):
    lat = row["lat_centroide"]
    lon = row["lon_centroide"]
    key = (round(lat, 6), round(lon, 6))
    ja_no_cache = key in cache          # verifica ANTES de consultar
    b = reverse_geocode_bairro(lat, lon)
    bairros.append(b)
    sufixo = " (cache)" if ja_no_cache else ""
    print(f"  [{i:>3}/{total}] ({lat:.5f}, {lon:.5f}) → {b}{sufixo}")

grade_cat["bairro"] = bairros

# ── Pós-processamento: substitui "Cataguases" pelo vizinho mais próximo ────────
SEM_BAIRRO = {"Cataguases", "N/D", ""}

mascara_sem = grade_cat["bairro"].isin(SEM_BAIRRO) | grade_cat["bairro"].isna()
n_sem = mascara_sem.sum()

if n_sem > 0:
    print(f"\n  Preenchendo {n_sem} célula(s) sem bairro pelo vizinho mais próximo...")

    # Centróides em CRS métrico para calcular distância
    grade_m2 = grade_cat.copy()
    pts_wgs = gpd.GeoSeries(
        gpd.points_from_xy(grade_cat["lon_centroide"], grade_cat["lat_centroide"]),
        crs="EPSG:4326", index=grade_cat.index
    ).to_crs(CRS_METRICO)
    grade_m2 = gpd.GeoDataFrame(grade_cat.copy(), geometry=pts_wgs, crs=CRS_METRICO)

    # Células COM bairro real
    tem_bairro = grade_m2[~mascara_sem].copy()

    if not tem_bairro.empty:
        from shapely.ops import nearest_points as _nearest_points

        for idx in grade_cat[mascara_sem].index:
            pt = grade_m2.loc[idx, "geometry"]
            if pt is None or pt.is_empty:
                continue
            # Encontra a célula com bairro real mais próxima
            dists = tem_bairro.geometry.distance(pt)
            idx_vizinho = dists.idxmin()
            bairro_vizinho = grade_cat.loc[idx_vizinho, "bairro"]
            grade_cat.loc[idx, "bairro"] = bairro_vizinho

        print(f"  ✓ {n_sem} célula(s) preenchida(s) pelo vizinho mais próximo")
    else:
        print("  Aviso: nenhuma célula com bairro real encontrada para usar como referência.")
# ──────────────────────────────────────────────────────────────────────────────

# Salva/atualiza cache
rows_cache = [{"lat": lat, "lon": lon, "bairro": b} for (lat, lon), b in cache.items()]
pd.DataFrame(rows_cache).to_csv(CACHE_CSV, index=False)
print(f"\n  ✓ Cache salvo: {CACHE_CSV.name}")

# ══════════════════════════════════════════════════════
#  5. MONTAR E SALVAR CSV
# ══════════════════════════════════════════════════════

print("\n[5/5] Gerando CSV...")

POP_COL = "TOTAL"
DOM_COL = "TOTAL_DOM"

for col, nome in [(POP_COL, "população"), (DOM_COL, "domicílios")]:
    if col not in grade_cat.columns:
        disponiveis = [c for c in grade_cat.columns if "TOT" in c or "POP" in c or "DOM" in c]
        raise ValueError(f"Coluna de {nome} '{col}' não encontrada. Disponíveis: {disponiveis}")

id_col = next(
    (c for c in grade_cat.columns if c in ("ID_UNICO", "ID", "OBJECTID", "FID", "GRIDCODE")),
    grade_cat.columns[0]
)

csv_df = pd.DataFrame({
    "id_grade"     : grade_cat[id_col].values,
    "lat_centroide": grade_cat["lat_centroide"].round(6).values,
    "lon_centroide": grade_cat["lon_centroide"].round(6).values,
    "populacao"    : pd.to_numeric(grade_cat[POP_COL], errors="coerce").fillna(0).astype(int).values,
    "domicilios"   : pd.to_numeric(grade_cat[DOM_COL], errors="coerce").fillna(0).astype(int).values,
    "bairro"       : grade_cat["bairro"].fillna("N/D").values,
    "zona"         : grade_cat["zona"].values,
    "area_km2"     : grade_cat["area_km2"].values,
    "municipio"    : MUNICIPIO_NOME,
    "cd_municipio" : COD_MUNICIPIO,
})

csv_df = csv_df.sort_values(
    ["lat_centroide", "lon_centroide"],
    ascending=[False, True]
).reset_index(drop=True)

csv_df.to_csv(OUTPUT_CSV, index=False, encoding="utf-8-sig")

# ══════════════════════════════════════════════════════
#  RESUMO FINAL
# ══════════════════════════════════════════════════════

print("\n" + "═" * 55)
print(f"  ✅  Arquivo salvo: dados/grade_cataguases.csv")
print(f"  📦  Células       : {len(csv_df):,}")
print(f"       🏙️  Urbanas  : {(csv_df['zona']=='urbana').sum():,}")
print(f"       🌿  Rurais   : {(csv_df['zona']=='rural').sum():,}")
print(f"  👥  População     : {csv_df['populacao'].sum():,}")
print(f"  🏠  Domicílios    : {csv_df['domicilios'].sum():,}")
print(f"  🗺️   Área total    : {csv_df['area_km2'].sum():.1f} km²")
n_bairros = csv_df[csv_df["bairro"] != "N/D"]["bairro"].nunique()
n_nd      = (csv_df["bairro"] == "N/D").sum()
print(f"  🏘️   Bairros       : {n_bairros} distintos  ({n_nd} células sem nome)")
print("═" * 55)
print("\nPrimeiras linhas do CSV:")
print(csv_df.head(8).to_string(index=False))