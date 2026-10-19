"use strict";

// Hermes deliberately grants its runtime owner and administrative group access.
// A POSIX ACL mask is reported as group mode bits, including for named users.
function isPrivateFile(stat) {
  return stat.isFile() && stat.uid === process.getuid() &&
    (stat.mode & 0o117) === 0 &&
    (!(stat.mode & 0o060) || stat.gid === process.getgid());
}

module.exports = {isPrivateFile};
