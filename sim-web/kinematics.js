/* URDF forward kinematics shared by the browser simulator and the Node test.
 * Mirrors softjaw/kinematics.py exactly: origin = T(xyz) Rz(yaw) Ry(pitch) Rx(roll),
 * then a rotation of q about the joint axis. Units: mm, rad. Matrices are 4x4 row-major arrays.
 */
(function (root) {
  function mul(a, b) {
    const o = new Array(16).fill(0);
    for (let i = 0; i < 4; i++) for (let j = 0; j < 4; j++) for (let k = 0; k < 4; k++) o[i * 4 + j] += a[i * 4 + k] * b[k * 4 + j];
    return o;
  }
  function hom(R, t) {
    return [R[0], R[1], R[2], t[0], R[3], R[4], R[5], t[1], R[6], R[7], R[8], t[2], 0, 0, 0, 1];
  }
  function rpy(r) {
    const [ro, pi, ya] = r, cr = Math.cos(ro), sr = Math.sin(ro), cp = Math.cos(pi), sp = Math.sin(pi), cy = Math.cos(ya), sy = Math.sin(ya);
    // Rz(yaw) * Ry(pitch) * Rx(roll)
    return [cy * cp, cy * sp * sr - sy * cr, cy * sp * cr + sy * sr,
            sy * cp, sy * sp * sr + cy * cr, sy * sp * cr - cy * sr,
            -sp, cp * sr, cp * cr];
  }
  function axisAngle(axis, q) {
    const n = Math.hypot(axis[0], axis[1], axis[2]), x = axis[0] / n, y = axis[1] / n, z = axis[2] / n;
    const c = Math.cos(q), s = Math.sin(q), C = 1 - c;
    return [c + x * x * C, x * y * C - z * s, x * z * C + y * s,
            y * x * C + z * s, c + y * y * C, y * z * C - x * s,
            z * x * C - y * s, z * y * C + x * s, c + z * z * C];
  }
  /** World frames: [base, joint1..joint6, tcp]. */
  function frames(robot, q) {
    let T = hom([1, 0, 0, 0, 1, 0, 0, 0, 1], robot.base);
    const out = [T];
    robot.joints.forEach((j, i) => {
      T = mul(mul(T, hom(rpy(j.rpy), j.xyz)), hom(axisAngle(j.axis, q[i]), [0, 0, 0]));
      out.push(T);
    });
    out.push(mul(T, hom(rpy(robot.end_link.rpy), robot.end_link.xyz)));
    return out;
  }
  const api = { frames, mul, rpy, axisAngle };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.SoftJawKin = api;
})(typeof window !== "undefined" ? window : globalThis);
