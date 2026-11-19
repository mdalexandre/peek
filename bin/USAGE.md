# peek: bounded views of a file or a command

Commands:

    peek file PATH [--lines A:B]
    peek run -- CMD [ARGS...]
    peek token PATH
    peek write PATH --lines A:B --token TOKEN --from SRC

For a file over 200 lines, use peek file instead of Read.

peek file shows lines 1 to 100 by default; --lines A:B picks a window (at most 100 lines).
peek run runs CMD with stdin closed, stdout and stderr merged, and exits with its code.
A long run prints the first 30 and last 20 lines and saves everything to a spill file.

To edit: peek token PATH first, then peek file to read, then peek write with that token; exit 3 means the file changed, so take a new token.

The last line tells you what to do:
- next: a command to run as printed to read on.
- end: the file window reached the last line.
- done: nothing more to read.

Errors print exit 2 (or the command's code), then error: and the cause.
