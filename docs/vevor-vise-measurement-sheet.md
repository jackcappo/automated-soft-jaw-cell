# VEVOR 5-inch vise fit check

Target product: VEVOR SKU `TQ5CDXZDZJMPKQ001V0`.

The published product dimensions are sufficient for an early collision box but
not for manufacturing a jaw that will bolt on. Measure both fixed and moving
jaws; inexpensive vises can vary by revision.

Record all values in millimeters:

| Measurement | Fixed jaw | Moving jaw |
|---|---:|---:|
| Existing jaw width | | |
| Existing jaw height | | |
| Existing jaw thickness | | |
| Number of mounting bolts | | |
| Bolt thread and pitch | | |
| Horizontal bolt center spacing | | |
| Bolt center to bottom of jaw | | |
| Counterbore diameter | | |
| Counterbore depth | | |
| Locating step width | | |
| Locating step height | | |
| Maximum unobstructed replacement-jaw height | | |

Also record:

- Vise body length and width with the swivel base removed.
- Height from table to the top of the vise body and to the jaw seat.
- Maximum opening with the proposed thick soft jaws installed.
- Leadscrew input geometry for the pneumatic drive: shaft shape, across-flat or
  hex dimension, available axial clearance, and required open/close turns.
- Measured torque needed to grip a Delrin blank without permanent deformation.
- Pneumatic actuator model, supply pressure, regulator range, and valve type.

Photograph the fixed-jaw seat, moving-jaw seat, bolt holes, leadscrew input, and
vise mounted on the Mini Mill table with a scale visible.

After measuring, copy the values into
`config/vises/vevor-5in-accu-lock.json`. The profile must not move from
`measurement_required` to `verified` until a printed or scrap test jaw bolts on,
seats fully, and repeats after removal and reinstallation.

