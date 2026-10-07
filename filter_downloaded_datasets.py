from pathlib import Path
import shutil

import duckdb

from visualize_annotation import visualize

RELEVANT_FILES_QUERY = """
INSTALL webbed FROM community;
LOAD webbed;
SELECT DISTINCT
  filename
FROM
  read_xml ('data/*.xml', filename = true)
WHERE
  name IN ['Arctium lappa', 'Heracleum sphondylium', 'Anthriscus sylvestris'];
"""

db = duckdb.connect(":memory:")
relevant_files = db.execute(RELEVANT_FILES_QUERY).fetchall()
output_dir = Path('visualized_data/')
for image in relevant_files:
    # Copy XML
    shutil.copy(Path(image[0]), output_dir.joinpath(Path(image[0]).name))
    # Copy JPG
    shutil.copy(Path(image[0].replace('.xml', '.jpg')), output_dir.joinpath(Path(image[0].replace('.xml', '.jpg')).name))    
    visualize(
        image_path=Path(image[0].replace('.xml', '.jpg')),
        xml_path=Path(image[0]),
        output_dir=output_dir
    )