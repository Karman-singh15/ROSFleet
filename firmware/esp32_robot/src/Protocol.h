/*
 * Protocol.h - parse one line of the host<->ESP32 protocol.
 *
 * Plain C strings and no Arduino types on purpose, so the parser compiles
 * and is tested natively on a laptop. Parsing untrusted bytes off a wire is
 * exactly the code that should not first be exercised on a moving robot.
 *
 * The parser NEVER touches hardware; it only decides what a line means.
 * main.cpp decides what to do about it.
 */
#ifndef PROTOCOL_H
#define PROTOCOL_H

#include <stdlib.h>
#include <string.h>

namespace protocol {

enum CommandType {
  CMD_NONE = 0,     // blank line, ignore
  CMD_VELOCITY,     // CMD,<linear>,<angular>
  CMD_PING,         // PING,<seq>
  CMD_RESET,        // RST
  CMD_CONFIG,       // CFG,<key>,<value>
  CMD_MALFORMED,    // recognised verb, unusable arguments
  CMD_UNKNOWN       // unrecognised verb
};

struct ParsedCommand {
  CommandType type;
  float linear;
  float angular;
  long seq;
  char key[12];
  float value;
};

inline bool isBlank(const char *text) {
  for (const char *p = text; *p; ++p) {
    if (*p != ' ' && *p != '\t' && *p != '\r' && *p != '\n') return false;
  }
  return true;
}

/*
 * Parse `line` into `out`. Returns false only for CMD_MALFORMED/CMD_UNKNOWN,
 * so the caller can report an ERR while still knowing what was attempted.
 *
 * Deliberately strict about field counts: a truncated "CMD,0.3" must be
 * REJECTED, not read as "drive forward with angular = garbage". A half-
 * applied velocity command is how a robot drives itself into a wall.
 */
inline bool parse(const char *line, ParsedCommand *out) {
  memset(out, 0, sizeof(*out));
  out->type = CMD_NONE;
  if (line == 0 || isBlank(line)) return true;

  // Copy into a bounded scratch buffer: never mutate the caller's memory,
  // and never read past a line that lacks a terminator.
  char buffer[128];
  strncpy(buffer, line, sizeof(buffer) - 1);
  buffer[sizeof(buffer) - 1] = '\0';

  // Trim trailing whitespace/CR so "CMD,0.1,0\r" parses like "CMD,0.1,0".
  size_t len = strlen(buffer);
  while (len > 0 && (buffer[len - 1] == '\r' || buffer[len - 1] == '\n' ||
                     buffer[len - 1] == ' ' || buffer[len - 1] == '\t')) {
    buffer[--len] = '\0';
  }

  char *saveptr = 0;
  const char *verb = strtok_r(buffer, ",", &saveptr);
  if (verb == 0) return true;

  if (strcmp(verb, "CMD") == 0) {
    const char *linearText = strtok_r(0, ",", &saveptr);
    const char *angularText = strtok_r(0, ",", &saveptr);
    if (linearText == 0 || angularText == 0) {
      out->type = CMD_MALFORMED;
      return false;
    }
    char *endLinear = 0;
    char *endAngular = 0;
    const float linear = strtof(linearText, &endLinear);
    const float angular = strtof(angularText, &endAngular);
    // strtof returns 0 for unparseable text, which would look like a valid
    // "stop" command. Insist that at least one character was consumed.
    if (endLinear == linearText || endAngular == angularText) {
      out->type = CMD_MALFORMED;
      return false;
    }
    out->type = CMD_VELOCITY;
    out->linear = linear;
    out->angular = angular;
    return true;
  }

  if (strcmp(verb, "PING") == 0) {
    const char *seqText = strtok_r(0, ",", &saveptr);
    out->type = CMD_PING;
    out->seq = (seqText != 0) ? strtol(seqText, 0, 10) : 0;
    return true;
  }

  if (strcmp(verb, "RST") == 0) {
    out->type = CMD_RESET;
    return true;
  }

  if (strcmp(verb, "CFG") == 0) {
    const char *keyText = strtok_r(0, ",", &saveptr);
    const char *valueText = strtok_r(0, ",", &saveptr);
    if (keyText == 0 || valueText == 0) {
      out->type = CMD_MALFORMED;
      return false;
    }
    char *endValue = 0;
    const float value = strtof(valueText, &endValue);
    if (endValue == valueText) {
      out->type = CMD_MALFORMED;
      return false;
    }
    out->type = CMD_CONFIG;
    strncpy(out->key, keyText, sizeof(out->key) - 1);
    out->value = value;
    return true;
  }

  out->type = CMD_UNKNOWN;
  return false;
}

}  // namespace protocol

#endif  // PROTOCOL_H
