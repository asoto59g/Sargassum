// ============================================================================
// SARGAZO CARIBE - V3  (NO OPERATIVO EN GEE TAL CUAL)
//
// Este script NO funciona como sistema de monitoreo:
// 1. PACE OCI no está en el catálogo público de GEE (el asset es un marcador).
// 2. El producto OC_AOP/Rrs de PACE solo llega ~719 nm; AFAI necesita 748 y 869 nm
//    (están en PACE L2 SFREFL, variable rhos).
// 3. La máscara marina es un rectángulo: el raster cubre tierra.
//
// Usa la app Python de esta carpeta:
//   .venv\Scripts\streamlit.exe run app.py
//   python -m sargazo --dias 3
//
// ============================================================================
// AFAI + SENTINEL-3 OLCI + PACE OCI
// Google Earth Engine
//
// Sentinel-3 OLCI : 300 m
// PACE OCI        : ~1.2 km
//
// OBJETIVO:
// Detectar Sargassum flotante en el Mar Caribe utilizando AFAI.
//
// CLASES:
// 0 = sin detección
// 1 = señal posible
// 2 = señal probable
// 3 = señal fuerte
//
// IMPORTANTE:
// PACE OCI NO está actualmente en el catálogo público de GEE.
// Debe cargarse mediante un asset/colección propia.
// ============================================================================


// ============================================================================
// 1. CONFIGURACIÓN
// ============================================================================

var DIAS = 7;


// -----------------------------------------------------------------------------
// PACE
// -----------------------------------------------------------------------------

// FALSE = solamente Sentinel-3
// TRUE  = Sentinel-3 + PACE

var USAR_PACE = false;


// -----------------------------------------------------------------------------
// Asset PACE
// -----------------------------------------------------------------------------
//
// REEMPLAZAR cuando tengas cargado PACE en GEE.
//
// Ejemplo:
// var PACE_ASSET =
//   'projects/ee-xxxxx/assets/PACE_OCI_CARIBE';
//
// -----------------------------------------------------------------------------

var PACE_ASSET =
  'projects/ee-TU_USUARIO/assets/PACE_OCI_CARIBE';


// -----------------------------------------------------------------------------
// Umbral AFAI Sentinel-3
// -----------------------------------------------------------------------------

var UMBRAL_AFAI_S3 = 0.0005;


// -----------------------------------------------------------------------------
// Umbral AFAI PACE
// -----------------------------------------------------------------------------

var UMBRAL_AFAI_PACE = 0.0005;


// -----------------------------------------------------------------------------
// Mínimo de píxeles conectados
// -----------------------------------------------------------------------------

var MIN_PIXELES = 3;


// ============================================================================
// 2. MAR CARIBE
// ============================================================================

var CARIBE = ee.Geometry.Rectangle([
  -89.0, 8.0,
  -58.0, 25.5
]);

Map.centerObject(
  CARIBE,
  5
);


// ============================================================================
// 3. FECHAS
// ============================================================================

var FECHA_FIN =
  ee.Date(
    Date.now()
  );

var FECHA_INICIO =
  FECHA_FIN.advance(
    -DIAS,
    'day'
  );


print(
  '=========================================='
);

print(
  'MONITOREO DE SARGAZO - V3'
);

print(
  'Inicio:',
  FECHA_INICIO.format(
    'YYYY-MM-dd'
  )
);

print(
  'Fin:',
  FECHA_FIN.format(
    'YYYY-MM-dd'
  )
);


// ============================================================================
// 4. MÁSCARA MARINA
// ============================================================================
//
// NO utilizamos NDWI para separar tierra.
//
// Creamos una máscara mediante la geometría del área oceánica.
// Para evitar costas y falsos positivos:
//
// dejamos un margen de seguridad alrededor de tierra.
//
// La geometría CARIBE es oceánica/regional y las imágenes se
// recortan posteriormente.
// ============================================================================


// -----------------------------------------------------------------------------
// Sentinel-3
// -----------------------------------------------------------------------------

var OCEANO =
  ee.Image.constant(1)
    .clip(CARIBE)
    .selfMask();


// ============================================================================
// 5. SENTINEL-3 OLCI
// ============================================================================

var S3 =
  ee.ImageCollection(
    'COPERNICUS/S3/OLCI'
  )
  .filterBounds(
    CARIBE
  )
  .filterDate(
    FECHA_INICIO,
    FECHA_FIN
  );

print(
  'Sentinel-3 imágenes:',
  S3.size()
);


// ============================================================================
// 6. AFAI SENTINEL-3
// ============================================================================
//
// AFAI:
//
// RED  = 665 nm
// NIR  = 708.75 / 754 / 865 nm
//
// Para aproximarnos al AFAI utilizado en sensores
// multiespectrales usamos:
//
// RED = Oa08 = 665 nm
// NIR = Oa12 = 753.75 nm
// NIR2 = Oa17 = 865 nm
//
// Esto evita utilizar el SWIR 1029 nm del cálculo FAI
// anterior.
//
// AFAI = R748 - línea base entre 667 y 869 nm.
//
// OLCI no tiene exactamente 748 nm, por lo que usamos
// Oa12 (753.75 nm) como aproximación.
// ============================================================================

function calcularAFAI_S3(
  imagen
) {

  var red =
    imagen
      .select(
        'Oa08_radiance'
      )
      .multiply(
        0.00876539
      );


  var nir =
    imagen
      .select(
        'Oa12_radiance'
      )
      .multiply(
        0.0071996
      );


  var nir865 =
    imagen
      .select(
        'Oa17_radiance'
      )
      .multiply(
        0.00493004
      );


  // --------------------------------------------------------------------------
  // Línea base
  // --------------------------------------------------------------------------

  var baseline =
    red.add(

      nir865
        .subtract(
          red
        )
        .multiply(
          (753.75 - 665) /
          (865 - 665)
        )

    );


  // --------------------------------------------------------------------------
  // AFAI
  // --------------------------------------------------------------------------

  var afai =
    nir
      .subtract(
        baseline
      )
      .rename(
        'AFAI'
      );


  return imagen
    .addBands(
      afai
    )
    .copyProperties(
      imagen,
      [
        'system:time_start'
      ]
    );
}


var S3_AFAI =
  S3.map(
    calcularAFAI_S3
  );


// ============================================================================
// 7. COMPOSICIÓN S3
// ============================================================================

var AFAI_S3 =
  S3_AFAI
    .select(
      'AFAI'
    )
    .median()
    .clip(
      CARIBE
    );


// ============================================================================
// 8. MÁSCARA DE CALIDAD S3
// ============================================================================
//
// Eliminamos píxeles con riesgo de sunglint.
//
// quality_flags:
// bit 22 = sun glint
// ============================================================================

function mascaraCalidadS3(
  imagen
) {

  var flags =
    imagen.select(
      'quality_flags'
    );


  var sunglint =
    flags.bitwiseAnd(
      1 << 22
    ).eq(0);


  return imagen
    .updateMask(
      sunglint
    );
}


var S3_QC =
  S3.map(
    mascaraCalidadS3
  );


// ============================================================================
// 9. VISUALIZACIÓN AFAI S3
// ============================================================================

Map.addLayer(
  AFAI_S3.updateMask(
    OCEANO
  ),
  {
    min: -0.002,
    max: 0.008,

    palette: [
      '000080',
      '0000FF',
      '00FFFF',
      '00FF00',
      'FFFF00',
      'FF8000',
      'FF0000'
    ]

  },
  'S3 AFAI',
  true
);


// ============================================================================
// 10. CANDIDATOS S3
// ============================================================================

var S3_CANDIDATO =
  AFAI_S3
    .gt(
      UMBRAL_AFAI_S3
    )
    .updateMask(
      OCEANO
    )
    .selfMask();


Map.addLayer(
  S3_CANDIDATO,
  {
    palette: [
      'FF0000'
    ]
  },
  'S3 - posible sargazo'
);


// ============================================================================
// 11. PACE OCI
// ============================================================================
//
// PACE no está en el catálogo público GEE.
//
// Si USAR_PACE = false,
// esta sección queda desactivada.
//
// ============================================================================

var PACE =
  ee.ImageCollection(
    PACE_ASSET
  )
  .filterBounds(
    CARIBE
  )
  .filterDate(
    FECHA_INICIO,
    FECHA_FIN
  );


// ============================================================================
// 12. INFORMACIÓN PACE
// ============================================================================

print(
  'PACE habilitado:',
  USAR_PACE
);

print(
  'PACE imágenes:',
  ee.Algorithms.If(
    USAR_PACE,
    PACE.size(),
    'Desactivado'
  )
);


// ============================================================================
// 13. AFAI PACE
// ============================================================================
//
// ATENCIÓN:
//
// Este bloque requiere que el asset PACE tenga bandas de
// reflectancia con nombres:
//
// Rrs_667
// Rrs_748
// Rrs_869
//
// Si el asset utiliza otros nombres, deben modificarse aquí.
//
// ============================================================================

function calcularAFAI_PACE(
  imagen
) {

  var red =
    imagen.select(
      'Rrs_667'
    );


  var nir =
    imagen.select(
      'Rrs_748'
    );


  var nir869 =
    imagen.select(
      'Rrs_869'
    );


  var baseline =
    red.add(

      nir869
        .subtract(
          red
        )
        .multiply(
          (748 - 667) /
          (869 - 667)
        )

    );


  var afai =
    nir
      .subtract(
        baseline
      )
      .rename(
        'PACE_AFAI'
      );


  return imagen
    .addBands(
      afai
    )
    .copyProperties(
      imagen,
      [
        'system:time_start'
      ]
    );
}


var PACE_AFAI =
  ee.ImageCollection(
    ee.Algorithms.If(
      USAR_PACE,

      PACE.map(
        calcularAFAI_PACE
      ),

      ee.ImageCollection([])
    )
  );


// ============================================================================
// 14. COMPOSICIÓN PACE
// ============================================================================

var AFAI_PACE =
  ee.Image(
    ee.Algorithms.If(

      USAR_PACE,

      PACE_AFAI
        .select(
          'PACE_AFAI'
        )
        .median()
        .clip(
          CARIBE
        ),

      ee.Image(0)
    )
  );


// ============================================================================
// 15. CANDIDATO PACE
// ============================================================================

var PACE_CANDIDATO =
  AFAI_PACE
    .gt(
      UMBRAL_AFAI_PACE
    )
    .updateMask(
      OCEANO
    )
    .selfMask();


Map.addLayer(
  PACE_CANDIDATO,
  {
    palette: [
      '00FFFF'
    ]
  },
  'PACE - posible sargazo',
  false
);


// ============================================================================
// 16. FUSIÓN S3 + PACE
// ============================================================================
//
// S3 = resolución 300 m
// PACE = resolución ~1.2 km
//
// NO utilizamos reproject().
//
// Se mantiene la proyección nativa de cada sensor.
// ============================================================================


// -----------------------------------------------------------------------------
// Caso sin PACE
// -----------------------------------------------------------------------------

var RESULTADO_BASE =
  S3_CANDIDATO;


// -----------------------------------------------------------------------------
// Cuando PACE está activo:
//
// PACE se utiliza como confirmación regional.
//
// Para evitar reproyección forzada,
// hacemos un "neighborhood" espacial sobre PACE.
//
// -----------------------------------------------------------------------------

var PACE_CONFIRMACION =
  PACE_CANDIDATO
    .focal_max({
      radius: 1200,
      units: 'meters'
    });


// ============================================================================
// 17. SCORE
// ============================================================================
//
// S3 = 1 punto
// PACE = 2 puntos
//
// Si ambos coinciden:
// SCORE = 3
//
// ============================================================================

var SCORE_S3 =
  S3_CANDIDATO
    .unmask(0)
    .multiply(1);


var SCORE_PACE =
  ee.Image(
    ee.Algorithms.If(
      USAR_PACE,

      PACE_CONFIRMACION
        .unmask(0)
        .multiply(2),

      ee.Image(0)
    )
  );


var SCORE =
  SCORE_S3
    .add(
      SCORE_PACE
    )
    .updateMask(
      OCEANO
    )
    .rename(
      'SCORE'
    );


// ============================================================================
// 18. CLASIFICACIÓN
// ============================================================================
//
// 1 = Sentinel-3 solamente
// 2 = PACE solamente
// 3 = coincidencia S3 + PACE
// ============================================================================

var CLASE =
  SCORE
    .where(
      SCORE.eq(1),
      1
    )
    .where(
      SCORE.eq(2),
      2
    )
    .where(
      SCORE.gte(3),
      3
    )
    .updateMask(
      SCORE.gt(0)
    )
    .rename(
      'SARGAZO'
    );


// ============================================================================
// 19. FILTRO ESPACIAL
// ============================================================================

var CONECTADOS =
  CLASE.connectedPixelCount(
    100,
    true
  );


var CLASE_FINAL =
  CLASE.updateMask(
    CONECTADOS.gte(
      MIN_PIXELES
    )
  );


// ============================================================================
// 20. MAPA FINAL
// ============================================================================

Map.addLayer(
  CLASE_FINAL,
  {
    min: 1,
    max: 3,

    palette: [
      'FFFF00',  // S3
      '00FFFF',  // PACE
      'FF0000'   // ambos
    ]

  },
  'SARGAZO - AFAI S3 + PACE'
);


// ============================================================================
// 21. RGB SENTINEL-3
// ============================================================================

var S3_RGB =
  S3
    .median()
    .select([
      'Oa08_radiance',
      'Oa06_radiance',
      'Oa04_radiance'
    ])
    .multiply(
      ee.Image([
        0.00876539,
        0.0123538,
        0.0115198
      ])
    )
    .clip(
      CARIBE
    );


Map.addLayer(
  S3_RGB,
  {
    min: 0,
    max: 6,
    gamma: 1.5
  },
  'Sentinel-3 RGB',
  false
);


// ============================================================================
// 22. ÁREA DETECTADA
// ============================================================================

var AREA =
  ee.Image.pixelArea()
    .divide(
      1000000
    )
    .rename(
      'area_km2'
    );


// -----------------------------------------------------------------------------
// S3
// -----------------------------------------------------------------------------

var AREA_S3 =
  AREA
    .updateMask(
      CLASE_FINAL.gte(1)
    )
    .reduceRegion({

      reducer:
        ee.Reducer.sum(),

      geometry:
        CARIBE,

      scale:
        300,

      maxPixels:
        1e10,

      bestEffort:
        true

    });


print(
  'Área total detectada S3/PACE (km²):',
  AREA_S3
);


// ============================================================================
// 23. ÁREA DE COINCIDENCIA
// ============================================================================

var AREA_ALTA =
  AREA
    .updateMask(
      CLASE_FINAL.eq(3)
    )
    .reduceRegion({

      reducer:
        ee.Reducer.sum(),

      geometry:
        CARIBE,

      scale:
        300,

      maxPixels:
        1e10,

      bestEffort:
        true

    });


print(
  'Área de coincidencia S3 + PACE (km²):',
  AREA_ALTA
);


// ============================================================================
// 24. POLÍGONOS
// ============================================================================
//
// Se vectoriza a 300 m, que corresponde a la escala de S3.
// ============================================================================

var POLIGONOS =
  CLASE_FINAL
    .selfMask()
    .reduceToVectors({

      geometry:
        CARIBE,

      scale:
        300,

      geometryType:
        'polygon',

      eightConnected:
        true,

      labelProperty:
        'clase',

      maxPixels:
        1e10,

      bestEffort:
        true

    });


// ============================================================================
// 25. ÁREA DE CADA MANCHA
// ============================================================================

POLIGONOS =
  POLIGONOS.map(
    function(feature) {

      var area =
        feature
          .geometry()
          .area()
          .divide(
            1000000
          );

      return feature.set(
        'area_km2',
        area
      );

    }
  );


print(
  'Número de manchas:',
  POLIGONOS.size()
);

print(
  'Primeras manchas:',
  POLIGONOS.limit(
    50
  )
);


// ============================================================================
// 26. POLÍGONOS EN MAPA
// ============================================================================

Map.addLayer(
  POLIGONOS.style({

    color:
      'FF0000',

    fillColor:
      '00000000',

    width:
      2

  }),

  {},

  'Manchas de sargazo',

  false
);


// ============================================================================
// 27. FECHAS SENTINEL-3
// ============================================================================

print(
  'Fechas Sentinel-3:',

  S3.aggregate_array(
    'system:time_start'
  )
  .map(
    function(t) {

      return ee.Date(t)
        .format(
          'YYYY-MM-dd'
        );

    }
  )
);


// ============================================================================
// 28. INFORMACIÓN FINAL
// ============================================================================

print(
  '=========================================='
);

print(
  'V3 - AFAI SARGAZO'
);

print(
  'Sentinel-3 OLCI = 300 m'
);

print(
  'PACE OCI = ~1.2 km'
);

print(
  'AFAI = detección de macroalgas flotantes'
);

print(
  'No se utiliza reproject()'
);

print(
  'No se utiliza NDVI como detector principal'
);

print(
  'No se utiliza NDWI para decidir tierra/mar'
);

print(
  '=========================================='
);