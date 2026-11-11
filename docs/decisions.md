# Design decisions

## Feeds reconnect forever, with exponential backoff and jitter
Connections drop in normal operation. Each failure doubles the wait (capped),
with random spread so many clients don't retry in lockstep. The wait resets
only after a real message arrives, not after merely connecting.

## A silent connection counts as a dead one
A socket can look open while nothing flows. If no message arrives within
`stale_after` seconds, we drop it and reconnect.

## Only connection errors are retried
`retry_on` lists the errors that mean "try again". Anything else is a bug in
our own code and crashes loudly instead of looping forever.

## One bad message never kills a connection
Unreadable messages are counted and skipped.

## Stopping a feed = cancelling its task
No custom stop flag. Cancelling closes the connection cleanly.