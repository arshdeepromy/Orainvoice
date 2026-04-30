# Native Platform Permissions

## iOS — Info.plist additions

Add the following keys to `ios/App/App/Info.plist`:

```xml
<key>NSCameraUsageDescription</key>
<string>OraInvoice needs camera access to capture photos for invoices, job cards, compliance documents, and expense receipts.</string>

<key>NSPhotoLibraryUsageDescription</key>
<string>OraInvoice needs photo library access to attach images to invoices, job cards, and compliance documents.</string>

<key>NSLocationWhenInUseUsageDescription</key>
<string>OraInvoice uses your location to record where job timers are started for accurate time tracking.</string>
```

## Android — AndroidManifest.xml additions

Add the following permissions to `android/app/src/main/AndroidManifest.xml`:

```xml
<uses-permission android:name="android.permission.CAMERA" />
<uses-permission android:name="android.permission.ACCESS_COARSE_LOCATION" />
<uses-permission android:name="android.permission.ACCESS_FINE_LOCATION" />
```

## Notes

- All Capacitor plugin calls are guarded with `isNativePlatform()` platform detection
- Camera falls back to `<input type="file">` on web
- Geolocation returns null silently on failure or permission denial
- Push notifications continue without push if permission denied
- Haptics no-op silently on web
- Network status assumes online if plugin unavailable
