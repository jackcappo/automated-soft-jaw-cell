# Third-party software and data

## Babylon.js
Loaded from jsDelivr (`babylonjs@7.54.3`) or `vendor/babylon.js`. Apache License 2.0.
- Project: https://www.babylonjs.com/
- Source: https://github.com/BabylonJS/Babylon.js

## reBot B601-DM model data
Joint origins, axes, limits and the end-link transform are copied into
`config/robots/rebot-b601-dm.json` from the public URDF. Mesh files are not redistributed.
- Source: https://github.com/Seeed-Projects/reBotArmController_ROS2
  (`src/rebotarm_bringup/description/DM/urdf/ReBot_Arm_DM.urdf`)

## Machine models
Downloaded machine CAD (for example the GrabCAD "Haas Mini Mill" model by Jonathan
Hernandez Rodriguez) belongs to its author. Import it locally with
`tools/import_machine_model.py`; `sim-web/assets/` is git-ignored so it is never committed.
