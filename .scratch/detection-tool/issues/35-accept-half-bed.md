# 35: Accept refuses a spider that can cross a ring

**What to build:** Accept refuses a bind whose far-double residual can move the model wire across the centre of an 8 mm ring. The Calibration view names the millimetres and the camera, not only a pass or warn word.

**Blocked by:** 22, 34

**Status:** ready-for-agent

Type: task
Model: auto

Half the distance from the centre of a double or treble ring to its wire is 4 mm. A far-double RMS above 2 mm, or a max above 4 mm, can put the model wire on the wrong side of a dart that is sitting in the middle of the ring. Do not raise these numbers so a live Board will pass.

- [ ] Accept blocks when far-double RMS is over 2 mm or the max is over 4 mm
- [ ] The Calibration view names those millimetres and which camera failed
- [ ] The synthetic distorted Board from 22 Accepts
- [ ] A homography-only foreshortened Board that passes on inlier RMS alone does not Accept
- [ ] The empty-Board capture from 22 either Accepts under this gate, or the answer stops and sends the fit back to 22
