-- Notification poster: item 1 = title, item 2 = body, item 3 = "sound".
-- Notifies only; nothing here ever needs dismissing.
on run argv
	set notifTitle to item 1 of argv
	set notifBody to item 2 of argv
	set wantsSound to false
	if (count of argv) > 2 then
		if item 3 of argv is "sound" then
			set wantsSound to true
		end if
	end if
	if wantsSound then
		display notification notifBody with title notifTitle sound name "Glass"
	else
		display notification notifBody with title notifTitle
	end if
end run
