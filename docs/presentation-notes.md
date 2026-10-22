# Friday presentation — 10 minutes

| # | Section (time) | What to say / show |
|---|---|---|
| 1 | Intro (1 min) | Team names, **RekogNail**: automatic product-photo thumbnails + AI label suggestions for small online sellers. |
| 2 | Problem (1 min) | Sellers photograph stock on their phones for WhatsApp Business, Instagram and online catalogues, then resize and sort the photos by hand. Inconsistent sizes and no descriptions make the catalogue messy. *Quote any seller interviews; say it's a hypothesis if you didn't validate it.* |
| 3 | Solution (1 min) | Upload a photo, get a ≤300 px thumbnail plus suggested labels in about 2 s. Serverless, so it costs nothing while idle and fractions of a cent per image. Labels are suggestions for a human to review. |
| 4 | Live demo (3 min) | Follow the [live demo script](#live-demo-script-3-minutes) below: real photo → fake file rejected → logs → test suite 7/7 → team gallery. |
| 5 | Tech (1 min) | Terraform, S3 (2 private buckets), Lambda Python 3.12 + Pillow layer, Rekognition, API Gateway, IAM least privilege, CloudWatch. Hardest part: browser uploads straight to private S3 (presigned POST + CORS + regional endpoint) and packaging Pillow for Lambda. |
| 6 | Challenges (1 min) | Avoiding the recursive trigger (separate buckets). Validating by content, not extension. Rekognition not available in Cape Town, so we use eu-west-1. Flat PNGs can get *bigger*. Logs lag CloudWatch by a few seconds. |
| 7 | Close + Q&A (2 min) | Results table from the README (real numbers). Next: Cognito accounts, DynamoDB catalogue, WhatsApp catalogue export, background removal. |

Likely questions: see [Q&A practice answers](#qa-practice-answers) at the bottom. Also: duplicate events are harmless, because processing is idempotent (the same key overwrites the same output).

---

## Live demo script (3 minutes)

### Before you present (10 minutes before)

1. **Open the live site** (`make url`) on the presenting laptop. Click **Settings** and enter your name and the team code (`make code`, or ask the team lead). The browser remembers both, so you won't type the code in front of everyone.
2. **Zoom the browser to 125–150%** so people at the back can read it.
3. **Put two files on the desktop:**
   - **A real product photo** you have already tried on the site, with labels that look good. A handbag fits the story best; Joe's ashwagandha photo also works (Herbal, Plant, Bottle). Don't use an untested photo, because the AI sometimes says odd things like "Weapon".
   - **A fake photo:** a text file renamed to `price-list.jpg`, or `test_images/generated/fake_text.jpg`.
4. **Upload one photo as a warm-up.** The first upload after a quiet period is about a second slower while AWS starts the code.
5. **Have a backup ready:** screenshots of each step, or a short screen recording, in case the Wi-Fi fails. Turn off notifications.

### The demo

| Time | Do | Say |
|---|---|---|
| 0:00–0:20 | Show the **Upload** tab. | "Meet Thandi. She sells handbags on WhatsApp and takes product photos on her phone. Those photos are large and messy to manage. Watch what happens when she uploads one." |
| 0:20–1:00 | Drag the **real photo** onto the drop zone. | While it processes (2–3 s): "The photo goes into a private, secure storage folder in the cloud. That automatically wakes up our program, which makes a small thumbnail and asks Amazon's image-recognition AI what's in the picture." Then point at three things. **Original vs thumbnail:** "Same photo, ready for a catalogue or WhatsApp." **Size reduction:** "Over 90% smaller, for example 2 MB down to about 20 KB. That means faster loading and less mobile data for her customers." **Labels:** "The AI suggests 'Handbag', 'Accessories'. These are suggestions. Thandi stays in control and can rate them with 👍/👎." |
| 1:00–1:30 | Drag **price-list.jpg** onto the drop zone. | "What if someone uploads something that isn't a photo?" When it's rejected: "It's rejected with a clear reason: not a readable image. Nothing crashes and nothing breaks." |
| 1:30–2:00 | Click **View logs** on the real photo's result. | "Every step is recorded live: the photo was received, then processed in about half a second. This is how we check the system is healthy." Point at one green *processed* line and the yellow warning for the rejected file. Don't read the technical fields out loud. |
| 2:00–2:40 | Click the **Test suite** tab, then **Run all checks** (takes about 20 s). | While it runs: "Our proposal listed seven requirements. This button tests all of them for real: it creates test photos and broken files, sends them through the live system, and checks each result." When it finishes: "Seven out of seven requirements pass." |
| 2:40–3:00 | Click the **Gallery** tab. | "This is every test our whole team ran this week: over 50 uploads, 100% of real images processed, and on average about 83% smaller." Hand over to the Technologies section. |

### Plain words for technical terms

| Instead of… | Say… |
|---|---|
| S3 bucket | "a secure, private online folder" |
| Lambda | "a small program that only runs when a photo arrives, so we pay per photo and nothing while it's idle" |
| Rekognition | "Amazon's image-recognition AI" |
| CloudWatch logs | "a live record of every step" |
| Presigned URL / API | skip it; save it for questions |

### If something goes wrong

- **The result is slow:** keep talking ("it's starting up"). It usually appears within about 5 seconds.
- **The Wi-Fi drops:** "This is a live system, so here's what it looks like." Switch to the screenshots or recording.
- **The AI gives an odd label:** use it. "This is exactly why labels are suggestions and a human reviews them."

### Tips

- **Rehearse three times with a timer.** The test suite step is the one most likely to run long; if you're short on time, skip the logs step.
- **Keep your hand off the mouse while you talk**, so people look at what you're pointing at.
- **Say the outcome before the detail.** For example, "it's 95% smaller" before "300 by 200 pixels".

---

## Q&A practice answers

Short enough to say out loud in 20–40 seconds. Numbers change as the team keeps testing, so check the live **Gallery** tab on the day.

**Numbers to have ready:** 45+ images processed · 100% of valid images processed · 13/13 bad files rejected · average about 82% smaller (93% on real photos) · about 0.8 s per image · about $0.10 per 100 images · 7/7 requirements pass.

### 1. Why AWS Lambda instead of an EC2 server?
"Our workload is short and comes in bursts. A photo arrives, takes under a second to process, and then nothing happens for a while. Lambda only runs when a photo arrives, and we pay per millisecond, so an idle system costs nothing. An EC2 server would run and bill 24/7, and we'd have to patch it and scale it ourselves. Lambda also scales automatically when more photos arrive. Lambda's limits, like 15 minutes per run, don't matter for images that take under a second."

### 2. Why two S3 buckets? Couldn't you use one?
"The main reason is to avoid an infinite loop. An upload triggers our function. If the function saved the thumbnail into the same bucket, that new file would trigger it again, forever. Separate buckets make that impossible. It's also more secure: the function can only *read* from the source bucket and only *write* to the output bucket. You *could* use one bucket with folder filters, and we filter on the `uploads/` folder too, but two buckets is safer and simpler to reason about."

### 3. What can your Lambda function do, and what are its permissions?
"It checks the file, using the actual content and not just the name: it must be a real JPEG or PNG, under 10 MB, and under 40 megapixels. It fixes phone rotation, shrinks the image to fit 300 by 300 while keeping its shape, optionally asks Rekognition for labels, and saves the thumbnail plus a small JSON result file. Its permissions are least-privilege. It can **read** files only in the source bucket's `uploads/` folder. It can **write** only to the output bucket's `thumbs/` and `meta/` folders. It can call Rekognition's DetectLabels and write its own logs. It can't delete or list anything, and it can't touch any other AWS service."

*If asked:* the Rekognition permission is granted for all resources (`*`) because AWS doesn't support narrowing it to specific ones for that action.

### 4. What if someone uploads a corrupt file or a PDF?
"It's rejected safely. A PDF is refused straight away because of its extension. A file renamed to `.jpg` is still caught, because we open it with the image library and it isn't a real image. A corrupt JPEG fails with 'truncated file'. Each rejected file gets a result with the reason and a warning in the logs. There's no crash and no thumbnail. Files over 10 MB never even reach storage, because the upload link itself enforces the limit. We tested this: 13 out of 13 bad files were rejected cleanly."

### 5. What is API Gateway doing? Is it required?
"It's the secure front door for our web page. It serves the page and hands out short-lived upload links so the browser can upload straight to our private bucket. It also returns results, shows logs, and records label votes. It enforces rate limits, and every request needs our team code. It isn't required for the core pipeline: S3 to Lambda works on its own, for example with uploads from the command line. We added it so teammates without AWS access could test, and to make the demo visual."

### 6. How does Rekognition work, and can we trust its labels?
"Rekognition is Amazon's pre-trained image-recognition AI. It's a deep-learning model trained on millions of labelled images. We send it a reference to the photo in S3, and it returns labels with confidence scores. We keep up to 10 labels above 70% confidence. Can we trust them? Only as *suggestions*. It's good at the general category: herbal product, car, handbag. But it makes mistakes. It called a herbal tin a 'Weapon' and labelled a chamomile tea photo 'Book'. It doesn't know brands or materials. That's why a human reviews the labels, and why we added 👍/👎 voting. We don't have enough votes yet to state a usefulness percentage."

### 7. How much does it cost? Is it cheaper than manual work?
"About **10 cents per 100 images** with AI labels. Almost all of that is Rekognition, at a tenth of a cent per image. Without labels it's about **0.3 cents per 100 images**. These are AWS list prices, without the Free Tier, which would cover a small seller completely. Is it cheaper than manual work? We haven't measured the manual side yet, so I won't claim a number. Our next step is to time a seller resizing photos by hand. Even at one minute per photo, 100 photos would take over an hour and a half, compared with about 10 cents and a couple of minutes."

### 8. What if 100 sellers upload at the exact same second?
"Honestly, we haven't load-tested that. Here's what the design does. Uploads go straight to S3, which handles that easily. S3 then queues an event for each photo. Our AWS account is new and can currently run 10 copies of the function at once, so the rest wait in Lambda's built-in queue and are retried automatically, for up to 6 hours. With about 0.8 seconds per photo, all 100 would finish within roughly 10 seconds. The limit people would actually notice is our API rate limit of 10 requests per second (bursts up to 20), which could make some upload buttons fail and need a retry. For real scale we'd raise both limits and add an SQS queue."

### 9. You mentioned 97.1% size reduction. How was it measured, and did any images miss the 50% target?
Correct the framing politely: 97.1% was the **median** in the README, not the average.

"Small correction: 97.1% was our *median*. The *average* is about 82%, and the number shifts slightly as the team keeps testing. We measured every image the same way: original bytes minus thumbnail bytes, divided by original bytes. The function calculates this and stores it with each result. On real teammate photos the average was 93%. And yes, some images missed the target: 6 out of 45. They were all images that were already tiny, like 120 by 80 pixels, which only shrink by re-saving. One transparent logo actually got **18% bigger**, because flat graphics already compress extremely well as PNG. That's a known limitation, and a fix would be to keep the original when the thumbnail comes out larger."

### 10. What was the hardest part, and what would you do differently?
"The hardest part was letting the browser upload directly to a *private* bucket. We needed temporary signed upload links, the right cross-site browser settings, and AWS's regional address, because the global one sends a redirect that browsers block. Packaging the Pillow image library for Lambda's Linux runtime was also tricky. And setting up automatic deploys from GitHub took some debugging, because GitHub's sign-in tokens used a newer ID format than we expected. If we did it again, we'd set up automatic deploys from day one, interview real sellers before building, measure manual time early, and use proper user accounts instead of a shared team code."
