# data/

Local scientific data (DANDI downloads, NWB files, video). Everything in this
folder except this README is ignored by git, so it never reaches GitHub.

Put each dataset in its own subfolder, e.g. `data/dandi/<dandiset-id>/`, and point
project configs (`projects/*/project.yaml`) at those paths.
