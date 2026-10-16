# Third-party notices

Base viewer licensing is documented in [LICENSE_STATUS.md](LICENSE_STATUS.md), with inherited and modified files listed in the [inventory](docs/licensing/base-viewer-files.json).

## Bundled components

| Component | Source and scope | Preserved license |
| --- | --- | --- |
| Three.js r169 | [mrdoob/three.js](https://github.com/mrdoob/three.js/tree/r169), including OrbitControls and STLLoader under `static/viewer/vendor/`; Copyright 2010–2024 Three.js Authors | [MIT](static/licenses/threejs.txt) |
| Unitree G1 description | [unitreerobotics/unitree_ros](https://github.com/unitreerobotics/unitree_ros), `robots/g1_description`; Copyright 2016–2022 HangZhou YuShu TECHNOLOGY CO., LTD | [BSD-3-Clause](static/licenses/unitree.txt) |
| WARP-RM core | [uynitsuj/WARP-RM](https://github.com/uynitsuj/WARP-RM), commit `26f9894abdaf883af8db78a38e164764e5bf7c00`; selected unmodified files in `vendor/warp_rm` | [MIT](vendor/warp_rm/LICENSE), [file provenance](vendor/warp_rm/provenance.json) |
| HFlow | [Hebbian-Robotics/hflow](https://github.com/Hebbian-Robotics/hflow); time, motion and numeric checks adapted in `quality_evidence.py` | [Apache-2.0](static/licenses/hflow.txt) |
| trajlens | [Kunal-Somani/trajlens](https://github.com/Kunal-Somani/trajlens); fixed-spacing and integrity-check ideas adapted in `quality_evidence.py` | [Apache-2.0](static/licenses/trajlens.txt) |
| Font Awesome Free 6.7.2 | [Font Awesome](https://fontawesome.com/), Fonticons, Inc.; selected unchanged SVG paths in `static/icons.svg` | [CC BY 4.0 icon attribution and license notice](static/licenses/fontawesome.txt) |

Robot mesh sources and hashes are recorded in [robot/SOURCE.json](robot/SOURCE.json), along with the modified `mid360_joint` origin in the URDF. Derived preview meshes retain the robot asset license.

## Optional model dependencies

The DINOv2-S/14 downloader uses Meta's [facebook/dinov2-small](https://huggingface.co/facebook/dinov2-small) at revision `ed25f3a31f01632728cabb09d1542f84ab7b0056` under [Apache-2.0](static/licenses/dinov2.txt). The separate model pack includes the backbone, license and SHA-256 provenance. The DINOv2 adaptation uses separately trained temporal weights.

DINOv3 weights require separate access and license terms and are not bundled.

Python dependencies retain their upstream licenses. Local model weights are optional for MiniMax review.
