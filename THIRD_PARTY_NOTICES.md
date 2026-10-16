# Third-party notices

The supplied base viewer still needs source and redistribution authorization verification. The exact 16 inherited/modified files are listed in [the inventory](docs/licensing/base-viewer-files.json); see [LICENSE_STATUS.md](LICENSE_STATUS.md). This notice does not apply a new license to those files.

## Bundled components

| Component | Source and scope | Preserved license |
| --- | --- | --- |
| Three.js r169 | [mrdoob/three.js](https://github.com/mrdoob/three.js/tree/r169), including OrbitControls and STLLoader under `static/viewer/vendor/`; Copyright 2010–2024 Three.js Authors | [MIT](static/licenses/threejs.txt) |
| Unitree G1 description | [unitreerobotics/unitree_ros](https://github.com/unitreerobotics/unitree_ros), `robots/g1_description`; Copyright 2016–2022 HangZhou YuShu TECHNOLOGY CO., LTD | [BSD-3-Clause](static/licenses/unitree.txt) |
| WARP-RM core | [uynitsuj/WARP-RM](https://github.com/uynitsuj/WARP-RM), commit `26f9894abdaf883af8db78a38e164764e5bf7c00`; selected unmodified files in `vendor/warp_rm` | [MIT](vendor/warp_rm/LICENSE), [file provenance](vendor/warp_rm/provenance.json) |
| HFlow | [Hebbian-Robotics/hflow](https://github.com/Hebbian-Robotics/hflow); time, motion and numeric checks adapted in `quality_evidence.py` | [Apache-2.0](static/licenses/hflow.txt) |
| trajlens | [Kunal-Somani/trajlens](https://github.com/Kunal-Somani/trajlens); fixed-spacing and integrity-check ideas adapted in `quality_evidence.py` | [Apache-2.0](static/licenses/trajlens.txt) |
| Font Awesome Free 6.7.2 | [Font Awesome](https://fontawesome.com/), Fonticons, Inc.; selected unchanged SVG paths in `static/icons.svg` | [CC BY 4.0 icon attribution and license notice](static/licenses/fontawesome.txt) |

The 35 original robot mesh files match the upstream Git blobs recorded in [robot/SOURCE.json](robot/SOURCE.json). The URDF differs at the fixed `mid360_joint` origin, as documented there. That supplied adjustment is retained, not presented as an unmodified upstream file. Generated preview meshes are derived from these assets; the same robot license is retained.

The current linear UI icons (`static/workspace-icons.svg`) and project mark are drawn for this project.

## Optional model dependencies

The public DINOv2-S/14 downloader uses Meta's official [facebook/dinov2-small](https://huggingface.co/facebook/dinov2-small) at revision `ed25f3a31f01632728cabb09d1542f84ab7b0056`. The model card identifies Apache-2.0; its [license](static/licenses/dinov2.txt) is preserved. The matching backbone is supplied in the separate Release model pack with its license; the source Git repository does not contain weight binaries. Downloads record SHA-256 provenance.

The original WARP-RM configuration uses DINOv3, whose weights have separate access and license terms. No DINOv3 weights or access credentials are distributed. The DINOv2 method adaptation uses separately trained temporal weights; a DINOv3-trained head is not used with DINOv2 features.

Python dependencies are installed from the requirements files and retain their upstream licenses. Development recordings, labels and feature caches are not distributed. Optional checkpoint metadata is retained for compatible playback tools; MiniMax review does not require local model weights.
