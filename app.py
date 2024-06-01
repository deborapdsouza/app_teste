import geemap
import geemap.foliumap as geemap
import ee
import streamlit as st
from streamlit_folium import folium_static
import plotly.express as px
import pandas as pd
from datetime import datetime

# Configuração da página
st.set_page_config(layout="wide")

st.title('APP NDVI SERIES')
st.divider()

st.sidebar.markdown("""Esta aplicação desenvolvida para visualização dos dados do Sentinel 2 utilizadas no cálculo de séries temporais de NDVI para municípios brasileiros""")

# Login geemap
ee.Initialize()

# Inserir roi
roi = ee.FeatureCollection('users/scriptsremoteambgeo/BR_Mun_2022')

# Botão de filtro da roi
# Adicionar um seletor de município
lista_estados = sorted(list(roi.aggregate_array('SIGLA_UF').distinct().getInfo()))
estado = st.selectbox("Selecione o município:", lista_estados)
roi_estado = roi.filter(ee.Filter.eq('SIGLA_UF', ee.String(estado)))

# Seleção do município
lista_municipios = sorted(list(roi_estado.aggregate_array('NM_MUN').distinct().getInfo()))
municipio = st.selectbox("Selecione o município:", lista_municipios)
roi_municipio = roi_estado.filter(ee.Filter.eq('NM_MUN', ee.String(municipio)))

# Define functions
def maskCloudAndShadowsSR(image):
    cloudProb = image.select('MSK_CLDPRB')
    snowProb = image.select('MSK_SNWPRB')
    cloud = cloudProb.lt(5)
    snow = snowProb.lt(5)
    scl = image.select('SCL')
    shadow = scl.eq(3)  # 3 = cloud shadow
    cirrus = scl.eq(10)  # 10 = cirrus
    # Probabilidade de nuvem inferior a 5% ou classificação de sombra de nuvem
    mask = (cloud.And(snow)).And(cirrus.neq(1)).And(shadow.neq(1))
    return image.updateMask(mask).select('B.*').multiply(0.0001).set('data', image.date().format('YYYY-MM-dd')).copyProperties(image, image.propertyNames())

# Cálculo do índice
def index(image):
    ndvi = image.normalizedDifference(['B8', 'B4']).rename('ndvi')
    evi = image.expression(
        '2.5 * ((NIR - RED) / (NIR + 6 * RED - 7.5 * BLUE + 1))',
        {
            'NIR': image.select('B8'),  # Infravermelho próximo
            'RED': image.select('B4'),  # Vermelho
            'BLUE': image.select('B2')  # Azul
        }
    ).rename('evi')
    savi = image.expression(
        '((NIR - RED) / (NIR + RED + L)) * (1 + L)',
        {
            'NIR': image.select('B8'),  # Infravermelho próximo
            'RED': image.select('B4'),  # Vermelho
            'L': 0.5  # Fator de ajuste do solo (0.5 para vegetação)
        }
    ).rename('savi')

    return image.addBands([ndvi, evi, savi]).clip(roi_municipio).copyProperties(image, image.propertyNames())

# Selecione a data de análise
dia_hoje = ee.Date(datetime.now())
dia_passado = dia_hoje.advance(-4, 'months')

# Formatar as datas para exibição
formatted_dia_hoje = dia_hoje.format('YYYY-MM-dd').getInfo()
formatted_dia_passado = dia_passado.format('YYYY-MM-dd').getInfo()

# Entrada de datas no Streamlit
start_date = st.sidebar.text_input('Data de Início', value=formatted_dia_passado)
end_date = st.sidebar.text_input('Data de Fim', value=formatted_dia_hoje)

# Slider para selecionar o percentual máximo de nuvens
max_cloud_percentage = st.sidebar.slider('Percentual Máximo de Nuvens', min_value=0, max_value=100, value=5)

# ImagemCollection
collection = ee.ImageCollection("COPERNICUS/S2_SR") \
    .filterBounds(roi_municipio) \
    .filterDate(start_date, end_date) \
    .filter(ee.Filter.lt('CLOUDY_PIXEL_PERCENTAGE', max_cloud_percentage)) \
    .map(maskCloudAndShadowsSR) \
    .map(index) \
    .select(['ndvi', 'savi', 'evi'])

# Selecione a imagem para aparecer no layer
data_images = list((collection.aggregate_array('data').distinct().getInfo()))
# Entrada de datas no Streamlit
data_select = st.selectbox('Selecione a data da imagem', data_images)

# Imagem selecionada
image_select = collection.filter(ee.Filter.eq('data', data_select)).median()

# Visualização dos dados
m = geemap.Map()
m.add_basemap('SATELLITE')
m.addLayer(roi_municipio, {}, 'Município')
m.addLayer(image_select.select('ndvi'), {'palette': ['red', 'yellow', 'green'], 'min': 0, 'max': 0.7}, 'NDVI {}'.format(str(data_select)))
m.addLayer(image_select.select('evi'), {'palette': ['red', 'yellow', 'green'], 'min': 0, 'max': 0.7}, 'EVI {}'.format(str(data_select)))
m.addLayer(image_select.select('savi'), {'palette': ['red', 'yellow', 'green'], 'min': 0, 'max': 0.7}, 'SAVI {}'.format(str(data_select)))
m.centerObject(roi_municipio, 10)
folium_static(m)

# Estatística
def reduce(image):
    serie_reduce = image.reduceRegions(**{
        'collection': roi_municipio,
        'reducer': ee.Reducer.mean(),
        'scale': 30
    })

    serie_reduce = serie_reduce.map(lambda f: f.set({'data': image.get('data')}))

    return serie_reduce.copyProperties(image, image.propertyNames())

# Aplicando a função de redução na Coleção
data_reduce = collection.map(reduce) \
    .flatten() \
    .sort('data', True) \
    .select(['NM_MUN', 'data', 'evi', 'ndvi', 'savi'])

st.divider()
df_stats = geemap.ee_to_df(data_reduce)

# Agrupar por data e calcular a média
df_stats_grouped = df_stats.groupby('data')[['ndvi', 'evi', 'savi']].mean().reset_index()

# Criar o gráfico de linhas com Plotly Express
fig = px.line(df_stats_grouped, x='data', y=['ndvi', 'evi', 'savi'],
              labels={'value': 'Índice', 'variable': 'Tipo de Índice'},
              title='Variação dos Índices NDVI, EVI e SAVI ao longo do Tempo',
              color_discrete_map={
                  'ndvi': 'green',
                  'evi': 'darkgreen',
                  'savi': 'lightgreen'
              })

# Exibir o gráfico e o DataFrame lado a lado no Streamlit
col1, col2 = st.columns([0.6, 0.4])

with col1:
    st.plotly_chart(fig)

with col2:
    st.dataframe(df_stats, width=600, height=400)

# Finalização do APP
st.divider()
st.sidebar.markdown('Desenvolvido por [AmbGEO]("https://ambgeo.com/")')
