Los granulos PACE OCI (`.nc`) **no se versionan**. Cada archivo SFREFL suele pesar 150–750 MB.

Coloca aquí las descargas de NASA Earthdata. La app y el CLI las buscan automáticamente:

```
data/PACE_OCI.YYYYMMDDTHHMMSS.L2.SFREFL.V3_1.NRT.nc
```

Para bajar datos nuevos usa la pestaña **Últimos días** de la app, o:

```bash
python -m sargazo --dias 3
```

Solo procesa productos **SFREFL**. Los archivos `OC_AOP` no sirven para AFAI (su Rrs termina ~719 nm).
