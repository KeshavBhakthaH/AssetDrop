package com.assetdrop.app;

import android.content.Intent;
import android.os.Bundle;
import com.getcapacitor.BridgeActivity;

public class MainActivity extends BridgeActivity {
    @Override
    public void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        handleSendIntent(getIntent());
    }

    @Override
    protected void onNewIntent(Intent intent) {
        super.onNewIntent(intent);
        setIntent(intent);
        handleSendIntent(intent);
    }

    private void handleSendIntent(Intent intent) {
        if (intent == null) return;
        String action = intent.getAction();
        String type = intent.getType();
        if (Intent.ACTION_SEND.equals(action) && type != null) {
            String sharedText = intent.getStringExtra(Intent.EXTRA_TEXT);
            if (sharedText != null && !sharedText.trim().isEmpty()) {
                final String safeText = sharedText.replace("\\", "\\\\").replace("'", "\\'").replace("\n", " ");
                getBridge().getWebView().post(new Runnable() {
                    @Override
                    public void run() {
                        String js = "if (window.handleSharedUrl) { window.handleSharedUrl('" + safeText + "'); } " +
                                    "else { window.__INITIAL_SHARED_URL = '" + safeText + "'; }";
                        getBridge().getWebView().evaluateJavascript(js, null);
                    }
                });
            }
        }
    }
}
