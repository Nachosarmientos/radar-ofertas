# Radar de Ofertas · plantilla

Una página web con ofertas de empleo que **se actualiza sola cada día**, gratis y sin inteligencia artificial.
Tú decides qué buscar y dónde; GitHub la busca, la filtra y la publica.

- **Coste:** 0 €. Usa GitHub Actions y GitHub Pages, gratuitos en repositorios públicos.
- **Mantenimiento:** ninguno. Solo tocas `config.yaml` si quieres cambiar algo.
- **Quien la visita** puede buscar, ordenar por plazo y guardar ofertas (se guardan en su propio navegador).

---

## Ponerlo en marcha (10 minutos)

1. **Crea tu copia.** Pulsa el botón verde **Use this template → Create a new repository**. Ponle un nombre y déjalo en **Public**.
2. **Edita `config.yaml`.** Ábrelo en GitHub, pulsa el lápiz ✏️ y cambia:
   - `titulo`, `subtitulo` y `color`
   - `palabras_clave` (lo que quieres) y `excluir` (lo que no)
   - en `fuentes`, pon `activa: true` en las que uses y rellena sus datos
   
   Pulsa **Commit changes**.
3. **Activa la página.** *Settings → Pages → Source: Deploy from a branch → Branch: `main` / carpeta `/docs`* → **Save**.
4. **Primera ejecución.** *Actions → Actualizar radar → Run workflow*. Al cabo de 1–2 minutos tu radar estará en
   `https://TU-USUARIO.github.io/NOMBRE-DEL-REPOSITORIO/`

Desde ahí se actualiza cada mañana y cada vez que guardes cambios en `config.yaml`.

> Si **Actions** da error de permisos: *Settings → Actions → General → Workflow permissions → Read and write permissions*.

---

## Fuentes disponibles

| Tipo | Para qué | Qué necesitas |
|---|---|---|
| `enlaces` | Páginas de empleo de organizaciones y portales | La URL y un `patron`: el trozo que comparten los enlaces de las ofertas (ej. `/empleo/ofertas/`) |
| `rss` | Cualquier feed RSS/Atom | La URL del feed |
| `fiiapp` | La tabla de ofertas de FIIAPP | Nada |
| `reliefweb` | Empleo humanitario y de desarrollo de todo el mundo | Un *appname* gratuito: se pide en [apidoc.reliefweb.int](https://apidoc.reliefweb.int/parameters#appname) |

**No se pueden leer sin navegador** (bloquean programas o cargan con JavaScript): InfoJobs, Indeed, Hacesfalta, Idealist, ReliefWeb web, Médicos del Mundo, Ayuda en Acción, ICMPD, CEAR, Cepaim y UN Tourism. LinkedIn tampoco: sus condiciones prohíben leerlo con programas.

**Truco: Google Alerts como fuente.** En [google.com/alerts](https://www.google.com/alerts) crea una alerta (ej. *"oferta técnico de proyectos cooperación"*),
pulsa *Mostrar opciones → Enviar a: Feed RSS*, crea la alerta y copia la URL del icono RSS. Pégala en una fuente `tipo: rss`.
Puedes añadir tantas alertas como quieras.

Para añadir otra fuente, copia un bloque entero (desde `- nombre:`) y cambia sus datos.

---

## Límites conocidos

- **LinkedIn no se puede leer**: bloquea los programas automáticos. Para LinkedIn, usa sus alertas de empleo por correo.
- El filtro es por **palabras**, no valora el encaje con un perfil. Para eso hace falta un análisis aparte.
- Las fuentes `web` dependen del diseño de cada página: si la página cambia, hay que ajustar los selectores.
- Si una fuente falla, el resto sigue funcionando; el pie de la página indica cuál no respondió.

---

## Estructura

```
config.yaml        ← lo único que editas
radar.py           busca, filtra y genera la página
plantilla.html     diseño de la página
data/ofertas.json  histórico de ofertas vigentes (se actualiza solo)
docs/index.html    la página publicada (se genera sola)
.github/workflows/ la programación diaria
```

Probar en tu ordenador (opcional): `pip install -r requirements.txt` y `python radar.py`.
