-- Nudge poster: the title, body, sound flag, and surface style arrive
-- through the DFN_TITLE, DFN_BODY, DFN_SOUND and DFN_STYLE environment
-- variables. Compiled applets on current macOS receive no command-line
-- arguments, so the environment is the only transport that survives a
-- direct binary launch. Missing values fall back to safe defaults: this
-- script never shows an error dialog.
--
-- DFN_STYLE selects the surface: "window" (the default) shows a centered
-- dialog that gives up on its own after 30 seconds, so nothing ever
-- blocks the machine; "notification" shows a standard notification.
on run
	set notifTitle to system attribute "DFN_TITLE"
	set notifBody to system attribute "DFN_BODY"
	set soundFlag to system attribute "DFN_SOUND"
	set styleFlag to system attribute "DFN_STYLE"
	if notifTitle is missing value then set notifTitle to ""
	if notifTitle is "" then set notifTitle to "DayflowNudge"
	if notifBody is missing value then set notifBody to ""
	if soundFlag is missing value then set soundFlag to ""
	if styleFlag is missing value then set styleFlag to ""
	if styleFlag is "notification" then
		if soundFlag is "sound" then
			display notification notifBody with title notifTitle sound name "Glass"
		else
			display notification notifBody with title notifTitle
		end if
	else
		if soundFlag is "sound" then beep 2
		display dialog notifBody with title notifTitle buttons {"Back to work"} default button 1 giving up after 30 with icon caution
	end if
end run
