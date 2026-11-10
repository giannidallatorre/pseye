# Patch: PS3EYEDriver teardown use-after-free

Two patches fix the same crash in
[inspirit/PS3EYEDriver](https://github.com/inspirit/PS3EYEDriver), which makes
`PS3EYECam::stop()` abort the process roughly 60% of the time on macOS when a
`pyvirtualcam` stream is running:

| Patch | Target |
|---|---|
| `0001-fix-transfer-teardown-use-after-free.patch` | upstream `master` (`src/ps3eye.cpp`, 1463 lines) |
| `0002-fix-transfer-teardown-use-after-free-pseyepy.patch` | the copy vendored by pseyepy (`pseyepy/src/ps3eye.cpp`, 1509 lines) |

They make the same four changes. The second exists because pseyepy's copy has
diverged from upstream (Windows `gettimeofday`, extra `debug()` calls, a
`Dequeue()` that returns a timestamp), so the upstream patch does not apply to it
as-is.

Upstream:

```bash
git clone https://github.com/inspirit/PS3EYEDriver
cd PS3EYEDriver
git apply -p1 /path/to/0001-fix-transfer-teardown-use-after-free.patch
```

pseyepy (from a checkout of https://github.com/bensondaled/pseyepy):

```bash
cd pseyepy
git apply -p1 /path/to/0002-fix-transfer-teardown-use-after-free-pseyepy.patch
```

## Symptom

Closing the camera aborts the process:

```
Assertion failed: (pthread_mutex_lock(mutex) == 0), function usbi_mutex_lock,
file threads_posix.h, line 46.
```

```
libusb_cancel_transfer
ps3eye::URBDesc::close_transfers()
ps3eye::PS3EYECam::stop()
ps3eye_close
Camera.end()
```

Measured on macOS 26.7.1 (Intel), libusb 1.0.30, pseyepy `79cf2fb`:

| Scenario | Crashes |
|---|---|
| `Camera(...)` + `cam.end()` in a bare script | 0 / 15 |
| Same, but with a `pyvirtualcam` stream running | **5 / 8** |

`pyvirtualcam` does not touch libusb; it only changes timing and CPU load, which
is what makes this a race rather than a deterministic failure.

## Root cause

`transfer_completed_callback()` frees a transfer when it completes with any
status other than `LIBUSB_TRANSFER_COMPLETED`:

```c
if (status != LIBUSB_TRANSFER_COMPLETED)
{
    libusb_free_transfer(xfr);      /* <-- frees it ... */
    urb->transfer_canceled();
    ...
}
```

...but `URBDesc::xfr[index]` still points at the freed transfer. `close_transfers()`
then walks the whole array and cancels every slot:

```c
for (int index = 0; index < NUM_TRANSFERS; ++index)
{
    libusb_cancel_transfer(xfr[index]);   /* <-- ... and cancels the freed one */
}
```

That is a use-after-free, and libusb turns it into an assertion failure. In
libusb 1.0.30 (`libusb/io.c`):

```c
void API_EXPORTED libusb_free_transfer(struct libusb_transfer *transfer)
{
    ...
    usbi_mutex_destroy(&itransfer->lock);   /* destroys the transfer's mutex */
    ...
    free(ptr);
}

int API_EXPORTED libusb_cancel_transfer(struct libusb_transfer *transfer)
{
    ...
    usbi_mutex_lock(&itransfer->lock);      /* locks the destroyed mutex */
    ...
}
```

`pthread_mutex_lock()` on a destroyed mutex returns `EINVAL`, and
`usbi_mutex_lock()` asserts on a non-zero return — exactly the message above.

The window is small: it needs a transfer to complete with a non-`COMPLETED`
status (an error, or a cancellation) at the same moment `stop()` is running.
That is why it is intermittent, and why it shows up under load.

There is a second, related defect: `xfr[]` is read by `close_transfers()` on the
calling thread while the completion callback writes to it on the transfer
thread, with no lock held across the free.

## Fix

1. `detach_transfer()` — new helper that clears the `xfr[]` slot for a transfer
   under `num_active_transfers_mutex`.
2. The completion callback calls `detach_transfer(xfr)` **before**
   `libusb_free_transfer(xfr)`, so the array never holds a dangling pointer.
3. `close_transfers()` skips `NULL` slots when cancelling, and frees whatever is
   left after the wait (clearing the slots), so the array is always consistent.
4. `xfr[]` is initialised to `NULL` in the constructor, so a `close_transfers()`
   that runs before `start_transfers()` cannot read uninitialised pointers.

## Known remaining hazard (not addressed here)

`transfer_completed_callback()` calls `urb->close_transfers()` for non-cancelled
error statuses. Because callbacks run on the transfer thread (inside
`libusb_handle_events_timeout_completed()`), and `close_transfers()` waits for
the remaining cancellation callbacks — which also need that same event loop —
that path can deadlock. It is a separate bug from the use-after-free fixed here
and is left alone to keep this patch minimal and reviewable.

## Use in this project

The patch is applied in the pseyepy fork this project pins
(`giannidallatorre/pseyepy@8338572`, commit `23624c2`), so `vcam.py` calls
`Camera.end()` on the way out: it stops the transfers, turns the LED off and
releases the USB interface. Ten consecutive `pseye off` + `pseye on` cycles are
clean. `vcam.py` still ends with `os._exit(0)` so that interpreter shutdown can
never hang.
