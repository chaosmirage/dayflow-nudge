-- Notification poster: title, body and the sound flag arrive through the
-- DFN_TITLE, DFN_BODY and DFN_SOUND environment variables. Compiled applets
-- on current macOS receive no command-line arguments, so the environment is
-- the only transport that survives a direct binary launch. Missing values
-- fall back to safe defaults: this script never shows an error dialog.
on run
	set notifTitle to system attribute "DFN_TITLE"
	set notifBody to system attribute "DFN_BODY"
	set soundFlag to system attribute "DFN_SOUND"
	if notifTitle is missing value then set notifTitle to ""
	if notifTitle is "" then set notifTitle to "DayflowNudge"
	if notifBody is missing value then set notifBody to ""
	if soundFlag is missing value then set soundFlag to ""
	if soundFlag is "sound" then
		display notification notifBody with title notifTitle sound name "Glass"
	else
		display notification notifBody with title notifTitle
	end if
end run
