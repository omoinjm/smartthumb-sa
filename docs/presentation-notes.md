# Friday presentation — 10 minutes

| # | Section (time) | What to say / show |
|---|---|---|
| 1 | Intro (1 min) | Team names, **SmartThumb SA**: automatic product-photo thumbnails + AI label suggestions for small online sellers. |
| 2 | Problem (1 min) | Sellers photograph stock on their phones for WhatsApp Business, Instagram and online catalogues, then resize and sort the photos by hand. Inconsistent sizes and no descriptions make the catalogue messy. *Quote any seller interviews; say it's a hypothesis if you didn't validate it.* |
| 3 | Solution (1 min) | Upload a photo, get a ≤300 px thumbnail plus suggested labels in about 2 s. Serverless, so it costs nothing while idle and fractions of a cent per image. Labels are suggestions for a human to review. |
| 4 | Live demo (3 min) | Follow the [live demo script](#live-demo-script-3-minutes) below: real photo → fake file rejected → logs → test suite 7/7 → team gallery. |
| 5 | Tech (1 min) | Terraform, S3 (2 private buckets), Lambda Python 3.12 + Pillow layer, Rekognition, API Gateway, IAM least privilege, CloudWatch. Hardest part: browser uploads straight to private S3 (presigned POST + CORS + regional endpoint) and packaging Pillow for Lambda. |
| 6 | Challenges (1 min) | Avoiding the recursive trigger (separate buckets). Validating by content, not extension. Rekognition not available in Cape Town, so we use eu-west-1. Flat PNGs can get *bigger*. Logs lag CloudWatch by a few seconds. |
| 7 | Close + Q&A (2 min) | Results table from the README (real numbers). Next: Cognito accounts, DynamoDB catalogue, WhatsApp catalogue export, background removal. |

Likely questions: Why two buckets? What does it cost per 100 images? What if Rekognition is wrong? How is it secured? What happens on duplicate events (it's idempotent: the same key overwrites the same output)?

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
